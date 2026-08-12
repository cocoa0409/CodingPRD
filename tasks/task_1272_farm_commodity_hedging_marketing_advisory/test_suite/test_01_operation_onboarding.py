"""Operation onboarding, baseline variants, validation cascade, RBAC basics."""
import pytest

from test_helpers import (
    validate_success,
    validate_error,
    get_success_data,
    is_valid_uuid,
    ApiErrorId,
    MISSING_UUID,
    TEST_USERS,
    make_grower_headers,
    create_operation_payload,
    create_baseline_payload,
    create_agreement_payload,
    create_plan_payload,
    create_market_tick_payload,
    assert_grower_operation,
    assert_production_baseline,
    assert_market_tick,
    create_operation,
    create_baseline_for,
)


class TestOperationCreation:
    def test_operation_create_defaults_and_system_fields(self, api):
        """PRD §3.1: "optionally a `yield_method` of `APH` or `TREND` which
        defaults to `APH` when omitted. The operation is created with
        `over_sold_flag` set to false."
        PRD §2.4: "The `id` is a server-minted UUID with no type prefix. The
        `created_at` and `updated_at` fields are ISO 8601 UTC timestamps with
        three fractional digits, derived from the server's logical clock. The
        `version` field is an integer that increments with every mutation to
        the resource and provides the basis for optimistic concurrency control."

        Design: Corner/entities/operation_create_defaults_and_system_fields
        """
        resp = api.create_operation(
            {
                "name": "Default Farm",
                "primary_commodity": "CORN",
                "crop_year": 2026,
                "risk_profile": "BALANCED",
            },
            TEST_USERS["advisor_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_grower_operation(data)
        assert data["yield_method"] == "APH", "omitted yield_method must default to APH"
        assert data["version"] == 1, f"new operation version must be 1, got {data['version']}"
        assert data["over_sold_flag"] is False, "over_sold_flag must start false"
        assert is_valid_uuid(data["id"])
        assert data["created_at"], "created_at must be present"

    def test_operation_missing_risk_profile_returns_400(self, api):
        """PRD §3.1: "onboarding a `GrowerOperation` with the operation's legal
        `name`, its `primary_commodity` (exactly one of `CORN`, `SOYBEAN`, or
        `WHEAT` per operation), the marketing `crop_year`, its `risk_profile`
        (`CONSERVATIVE`, `BALANCED`, or `AGGRESSIVE`), and optionally a
        `yield_method` of `APH` or `TREND` which defaults to `APH` when omitted."
        PRD §2.6: "Field-level schema validation runs third — missing required
        fields, invalid enum values, out-of-range values, violated
        conditional-field rules, or window inversions produce `ERR_VALIDATION`."

        Design: Corner/entities/operation_missing_risk_profile_returns_400
        """
        resp = api.create_operation(
            {"name": "Bad Farm", "primary_commodity": "CORN", "crop_year": 2026},
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)
        # Nothing persisted: the same payload with the required field succeeds.
        ok = api.create_operation(
            {
                "name": "Bad Farm",
                "primary_commodity": "CORN",
                "crop_year": 2026,
                "risk_profile": "BALANCED",
            },
            TEST_USERS["advisor_headers"],
        )
        validate_success(ok, expected_status=201)

    def test_get_operation_not_found_returns_404(self, api):
        """PRD §4: "Where a path contains a resource identifier, the system
        resolves it to an existing resource before any business rule is
        evaluated, failing with `ERR_NOT_FOUND` when the identifier does not
        resolve."

        Design: Corner/entities/get_operation_not_found_returns_404
        """
        resp = api.get_operation(MISSING_UUID, TEST_USERS["advisor_headers"])
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestBaselineVariants:
    def test_expected_bushels_aph_operation_selects_aph_variant(self, api):
        """PRD §3.1: "The `expected_bushels_aph` variant is the floor of
        `planted_acres` multiplied by `aph_yield_bushels`; it ignores the trend
        yield and the risk profile entirely. The `expected_bushels_trend`
        variant is the floor of `planted_acres` multiplied by
        `trend_yield_bushels` multiplied by a risk trend factor that is 0.98
        for `CONSERVATIVE`, 1.00 for `BALANCED`, and 1.02 for `AGGRESSIVE`;
        identical inputs therefore produce a different `expected_bushels_trend`
        than the APH variant produces for the same baseline. The operative
        `expected_bushels` field then takes the APH variant when the
        operation's `yield_method` is `APH` and the trend variant when it is
        `TREND`."

        Design: Difficulty/dual_variant_calc/expected_bushels_aph_vs_trend_diverge
        """
        op = create_operation(
            name="Farm A", primary_commodity="CORN", crop_year=2026,
            risk_profile="BALANCED", yield_method="APH",
        )
        baseline = create_baseline_for(
            op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205
        )
        assert_production_baseline(baseline)
        assert baseline["expected_bushels_aph"] == 20000, (
            f"floor(100 * 200) must be 20000, got {baseline['expected_bushels_aph']}"
        )
        assert baseline["expected_bushels_trend"] == 20500, (
            f"floor(100 * 205 * 1.00) must be 20500, got {baseline['expected_bushels_trend']}"
        )
        assert baseline["expected_bushels"] == 20000, (
            "APH operation must select the APH variant"
        )

    def test_expected_bushels_trend_operation_diverges_on_identical_inputs(self, api):
        """PRD §3.1: "identical inputs therefore produce a different
        `expected_bushels_trend` than the APH variant produces for the same
        baseline. The operative `expected_bushels` field then takes the APH
        variant when the operation's `yield_method` is `APH` and the trend
        variant when it is `TREND`."

        Design: Difficulty/dual_variant_calc/expected_bushels_aph_vs_trend_diverge
        """
        op = create_operation(
            name="Farm B", primary_commodity="CORN", crop_year=2026,
            risk_profile="BALANCED", yield_method="TREND",
        )
        baseline = create_baseline_for(
            op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205
        )
        assert baseline["expected_bushels_aph"] == 20000
        assert baseline["expected_bushels_trend"] == 20500
        assert baseline["expected_bushels"] == 20500, (
            "TREND operation must select the trend variant — identical inputs, "
            "different operative result than the APH sibling"
        )

    def test_baseline_computed_field_input_ignored(self, api):
        """PRD §3.1: "From these inputs the server computes two expected-bushel
        variants. The `expected_bushels_aph` variant is the floor of
        `planted_acres` multiplied by `aph_yield_bushels`; it ignores the trend
        yield and the risk profile entirely."

        Design: Corner/entities/baseline_computed_field_input_ignored
        """
        op = create_operation(
            name="Smuggle Farm", primary_commodity="CORN", crop_year=2026,
            risk_profile="BALANCED",
        )
        payload = create_baseline_payload(
            op["id"], op["version"],
            planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205,
        )
        payload["expected_bushels"] = 999  # client-smuggled computed field
        data = validate_success(api.create_baseline(payload, TEST_USERS["advisor_headers"]), expected_status=201)
        assert data["expected_bushels"] == 20000, (
            f"server-computed expected_bushels must be 20000, not the smuggled 999; got "
            f"{data['expected_bushels']}"
        )


class TestMarketTickAppendOnly:
    def test_market_tick_append_only_no_update_endpoint(self, api):
        """PRD §2.4: "One resource deviates from this convention: a
        `MarketTick` is an immutable price-feed record that carries only `id`
        and `created_at`; both `updated_at` and `version` are absent from it."
        PRD §2.11: "The price feed is a sequence of `MarketTick` records, each
        carrying a `commodity` (`CORN`, `SOYBEAN`, or `WHEAT`), a
        `contract_month` in `YYYY-MM` form, a `price` at four decimal places, a
        `kind` of either `QUOTE` or `SETTLEMENT`, and a `price_date`."

        Design: Corner/entities/market_tick_append_only_no_update_endpoint
        """
        resp = api.create_market_tick(
            {
                "commodity": "CORN",
                "contract_month": "2026-12",
                "price": 4.60,
                "kind": "SETTLEMENT",
                "price_date": "2026-06-01",
            },
            TEST_USERS["admin_headers"],
        )
        data = validate_success(resp, expected_status=201)
        assert_market_tick(data)
        assert data["price"] == pytest.approx(4.60)
        assert "updated_at" not in data, "append-only tick must not carry updated_at"
        assert "version" not in data, "append-only tick must not carry version"


class TestValidationCascadeOrdering:
    def test_certify_missing_baseline_returns_404(self, api):
        """PRD §2.6: "Fourth, every path identifier and every foreign-key
        reference in the request body must resolve to an existing resource, or
        the request fails with `ERR_NOT_FOUND`." and "A request failing an
        earlier check never reaches a later one, so the returned error always
        identifies the highest-priority violation present."

        Design: Corner/validations/certify_missing_baseline_returns_404
        """
        op = create_operation(
            name="P404 Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        resp = api.certify_baseline(MISSING_UUID, make_grower_headers(op["id"]))
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_policy_invalid_coverage_step_returns_400(self, api):
        """PRD §3.2: "The coverage level must lie between 0.50 and 0.85
        inclusive and move in steps of 0.05; any other value is a schema
        violation."
        PRD §2.6: "Field-level schema validation runs third — missing required
        fields, invalid enum values, out-of-range values, violated
        conditional-field rules, or window inversions produce `ERR_VALIDATION`.
        Fourth, every path identifier and every foreign-key reference in the
        request body must resolve to an existing resource, or the request fails
        with `ERR_NOT_FOUND`."

        Design: Corner/validations/policy_invalid_coverage_step_returns_400
        """
        op = create_operation(
            name="P400 Farm", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        resp = api.create_policy(
            {
                "operation_id": op["id"],
                "baseline_id": MISSING_UUID,
                "coverage_level_pct": 0.77,  # off the 0.05 step
                "projected_price": 4.50,
            },
            TEST_USERS["advisor_headers"],
        )
        validate_error(resp, ApiErrorId.ERR_VALIDATION)


class TestRbacBasics:
    def test_grower_cannot_create_plan(self, api):
        """PRD §4: the `POST /advisory/marketing-plans` row lists only
        `CommodityAdvisor` as its authorized role.
        PRD §2.1: "A request whose authenticated role is not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/grower_cannot_create_plan
        """
        op = create_operation(
            name="RBAC Farm 1", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        baseline = create_baseline_for(op, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        grower = make_grower_headers(op["id"])
        get_success_data(api.certify_baseline(baseline["id"], grower))
        resp = api.create_plan(
            {"operation_id": op["id"], "baseline_id": baseline["id"], "max_priced_pct": 0.80},
            grower,
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)

    def test_advisor_cannot_approve_buyer(self, api):
        """PRD §4: the `POST /advisory/buyers/{buyerId}/approve` row lists only
        `ComplianceOfficer` as its authorized role.
        PRD §2.1: "A request whose authenticated role is not listed among the
        roles authorized for the target endpoint is rejected with
        `ERR_FORBIDDEN_ROLE` (HTTP 403)."

        Design: Corner/rbac/advisor_cannot_approve_buyer
        """
        buyer = get_success_data(
            api.create_buyer(
                {"name": "RBAC Buyer", "buyer_type": "ELEVATOR", "credit_rating": "A"},
                TEST_USERS["advisor_headers"],
            )
        )
        resp = api.approve_buyer(buyer["id"], TEST_USERS["advisor_headers"])
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
        still = get_success_data(api.get_buyer(buyer["id"], TEST_USERS["advisor_headers"]))
        assert still["status"] == "PROVISIONAL", "buyer must remain PROVISIONAL after the forbidden call"

    def test_grower_cannot_certify_other_operations_baseline(self, api):
        """PRD §2.1: "A `Grower` request whose `X-User-ID` does not equal the
        operation id that owns the target resource is rejected with
        `ERR_RESOURCE_NOT_OWNED` (HTTP 403)."
        PRD §3.1: "Certification is the grower's attestation: a `Grower` whose
        `X-User-ID` equals the baseline's `operation_id` may certify the
        baseline, moving it from `PROVISIONAL` to `CERTIFIED` and incrementing
        the baseline's `version` by one."

        Design: Corner/rbac/grower_cannot_certify_other_operations_baseline
        """
        op_a = create_operation(
            name="Owner A", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        op_b = create_operation(
            name="Owner B", primary_commodity="CORN", crop_year=2026, risk_profile="BALANCED"
        )
        bl_a = create_baseline_for(op_a, planted_acres=100, aph_yield_bushels=200, trend_yield_bushels=205)
        resp = api.certify_baseline(bl_a["id"], make_grower_headers(op_b["id"]))
        validate_error(resp, ApiErrorId.ERR_RESOURCE_NOT_OWNED)
        still = get_success_data(api.get_baseline(bl_a["id"], TEST_USERS["advisor_headers"]))
        assert still["status"] == "PROVISIONAL", "baseline must stay PROVISIONAL after the ownership rejection"

    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request that omits either header, or carries a role
        value outside this enumeration, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."
        PRD §2.6: "Authentication is checked first — missing or unknown headers
        surface as `ERR_UNAUTHENTICATED` before anything else is examined."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        resp = api.create_operation(
            {"name": "Anon Farm", "primary_commodity": "CORN", "crop_year": 2026, "risk_profile": "BALANCED"},
            {"Content-Type": "application/json"},  # no X-User-ID / X-User-Role
        )
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)


class TestErrorEnvelope:
    def test_error_envelope_shape(self, api):
        """PRD §2.2: "All error API responses (4xx status codes) follow this
        standard envelope format:" — the envelope's `response_type` is `error`.
        PRD §2.2: "The `error_id` is a unique, machine-readable string that identifies the specific error."
        PRD §2.2: "The `message` provides a human-readable explanation of what went wrong."

        Design: Corner/errors/error_envelope_shape
        """
        resp = api.get_buyer(MISSING_UUID, TEST_USERS["advisor_headers"])
        body = resp.json()
        assert body.get("response_type") == "error", (
            f"error envelope must carry response_type == 'error', got {body.get('response_type')}"
        )
        assert body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert isinstance(body["data"]["message"], str) and body["data"]["message"], (
            "error data.message must be a non-empty string"
        )
