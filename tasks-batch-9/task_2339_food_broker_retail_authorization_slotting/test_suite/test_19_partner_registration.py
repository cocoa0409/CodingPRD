"""Registering trading partners: declared defaults, system fields and mandatory input."""

from test_helpers import (
    ACCOUNT_MANAGER_HEADERS,
    BROKER_ADMIN_HEADERS,
    DEFAULT_AT_RISK_VOID_RATE_BPS,
    DEFAULT_DEDUCTION_DISPUTE_WINDOW_DAYS,
    DEFAULT_DEMO_CHANGEOVER_BUFFER_MINUTES,
    DEFAULT_MAX_CONCURRENT_DEMOS,
    DEFAULT_REVIEW_BLACKOUT_DAYS,
    NON_EXISTENT_UUID,
    ApiErrorId,
    CreditPosture,
    PrincipalStatus,
    VoidRateBasis,
    fixtures,
    get_success_data,
    is_valid_uuid,
    make_retailer_buyer_headers,
    validate_error,
    validate_paginated,
)
from test_helpers import factories as F
from test_helpers.assertions import assert_principal, assert_retailer


class TestRetailerRegistrationDefaults:
    def test_every_omitted_policy_knob_lands_on_its_declared_default(self, api):
        """Three inputs in, six policy defaults out.

        PRD: "The chain record is also where the retailer's operating policy lives, and each
        policy field has a declared default that applies when the field is omitted at
        registration."

        Design: Corner/entities/retailer_creation_applies_every_declared_default_and_envelope
        """
        response = api.create_retailer(F.retailer_payload(), BROKER_ADMIN_HEADERS)
        retailer = get_success_data(response, 201)

        assert_retailer(retailer)
        assert retailer["void_rate_basis_default"] == VoidRateBasis.STORE_COUNT_BASIS
        assert retailer["at_risk_void_rate_bps"] == DEFAULT_AT_RISK_VOID_RATE_BPS
        assert retailer["deduction_dispute_window_days"] == DEFAULT_DEDUCTION_DISPUTE_WINDOW_DAYS
        assert (
            retailer["demo_changeover_buffer_minutes"]
            == DEFAULT_DEMO_CHANGEOVER_BUFFER_MINUTES
        )
        assert retailer["max_concurrent_demos"] == DEFAULT_MAX_CONCURRENT_DEMOS
        assert retailer["review_blackout_days"] == DEFAULT_REVIEW_BLACKOUT_DAYS
        assert retailer["version"] == 1
        assert is_valid_uuid(retailer["id"])

    def test_the_creation_body_and_the_read_agree_immediately(self, api):
        """A read straight after the write sees exactly the same record.

        PRD: "The `data` field contains the resource object or an array of resource objects. For
        2xx responses with no data, it contains an empty object. Unless otherwise noted,
        operations that create or modify a resource will return the created or updated resource
        object in the data field."

        Design: Corner/entities/retailer_creation_applies_every_declared_default_and_envelope
        """
        created = api.create_retailer(F.retailer_payload(), BROKER_ADMIN_HEADERS)
        body = created.json()
        assert body["response_type"] == "object"
        assert "api_request_id" in body["meta"]
        assert "api_request_timestamp" in body["meta"]

        written = body["data"]
        read_back = get_success_data(api.get_retailer(written["id"], ACCOUNT_MANAGER_HEADERS), 200)
        assert read_back == written


class TestPrincipalOnboardingSystemFields:
    def test_a_fresh_principal_reads_prospect_with_every_aggregate_at_zero(self, api):
        """None of the aggregates is caller-supplied, so all of them start empty.

        PRD: "A newly onboarded principal begins with `status` set to `PROSPECT`, with
        `slotting_committed_cents`, `open_slotting_liability_cents`, `open_deduction_cents`,
        `at_risk_authorization_count` and `liability_ratio_bps` all at 0, and with
        `credit_posture` at `NORMAL`."

        Design: Corner/entities/principal_system_and_computed_fields_start_at_declared_values
        """
        principal = get_success_data(
            api.create_principal(F.principal_payload(), BROKER_ADMIN_HEADERS), 201
        )

        assert_principal(principal)
        assert principal["status"] == PrincipalStatus.PROSPECT
        assert principal["slotting_committed_cents"] == 0
        assert principal["open_slotting_liability_cents"] == 0
        assert principal["open_deduction_cents"] == 0
        assert principal["at_risk_authorization_count"] == 0
        assert principal["liability_ratio_bps"] == 0
        assert principal["credit_posture"] == CreditPosture.NORMAL
        assert principal["version"] == 1

    def test_the_declared_start_values_are_visible_through_the_list_filters(self, api):
        """The new principal answers to status PROSPECT and to no restricted posture.

        PRD: "Principals may be filtered by `code`, by `status` and by `credit_posture`."

        Design: Corner/entities/principal_system_and_computed_fields_start_at_declared_values
        """
        principal = fixtures.create_principal(api)

        prospects, prospect_meta = validate_paginated(
            api.list_principals(BROKER_ADMIN_HEADERS, {"status": PrincipalStatus.PROSPECT})
        )
        assert prospect_meta["total_count"] == 1
        assert prospects[0]["id"] == principal["id"]

        _, restricted_meta = validate_paginated(
            api.list_principals(
                BROKER_ADMIN_HEADERS, {"credit_posture": CreditPosture.RESTRICTED}
            )
        )
        assert restricted_meta["total_count"] == 0


class TestMandatoryCreationInput:
    def test_each_omitted_mandatory_field_is_a_malformed_request(self, api):
        """Store count, budget and upc are all required, not defaulted.

        PRD: "A `BrokerAdmin` registers a retail chain with its `name`, a `chain_code` of 1 to
        16 characters drawn from uppercase letters, digits and underscores, and a
        `total_store_count` of at least one store."

        Design: Corner/entities/creations_missing_required_input_fields_are_rejected
        """
        principal = fixtures.create_principal(api)

        validate_error(
            api.create_retailer({"name": "Bigmart", "chain_code": "BIGMART"}, BROKER_ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_principal({"name": "Sunglow Frozen", "code": "SGF"}, BROKER_ADMIN_HEADERS),
            ApiErrorId.INVALID_REQUEST,
            400,
        )
        validate_error(
            api.create_item(
                {
                    "principal_id": principal["id"],
                    "description": "Mini Tacos 12ct",
                    "case_pack_units": 12,
                    "list_price_cents": 2010,
                    "unit_cost_cents": 1200,
                },
                ACCOUNT_MANAGER_HEADERS,
            ),
            ApiErrorId.INVALID_REQUEST,
            400,
        )

    def test_a_rejected_creation_persists_nothing(self, api):
        """The refused writes leave both collections empty.

        PRD: "**Request shape.** Required body fields present; types, enum membership and
        numeric ranges valid — for example `amortization_periods` between 1 and 12, `item_ids`
        holding 1 to 5 elements, every basis-point field within 0 through 10,000, `upc` exactly
        twelve digits, dates well-formed."

        Design: Corner/entities/creations_missing_required_input_fields_are_rejected
        """
        api.create_retailer({"name": "Bigmart", "chain_code": "BIGMART"}, BROKER_ADMIN_HEADERS)

        _, retailer_meta = validate_paginated(api.list_retailers(BROKER_ADMIN_HEADERS))
        assert retailer_meta["total_count"] == 0
        _, item_meta = validate_paginated(api.list_items(ACCOUNT_MANAGER_HEADERS))
        assert item_meta["total_count"] == 0

    def test_the_shape_band_is_reported_before_the_unknown_parent(self, api):
        """A review missing its deadline fails on shape even though its chain is unknown too.

        PRD: "Validations are evaluated in ascending priority bands, and the **first** violated
        rule determines the response."

        Design: Corner/entities/creations_missing_required_input_fields_are_rejected
        """
        response = api.create_review(
            {
                "retailer_id": NON_EXISTENT_UUID,
                "category_code": "FROZEN_SNACKS",
                "review_window_start": "2026-09-01",
                "review_window_end": "2026-09-15",
                "new_item_slots": 2,
            },
            make_retailer_buyer_headers(NON_EXISTENT_UUID),
        )

        validate_error(response, ApiErrorId.INVALID_REQUEST, 400)
        assert ApiErrorId.RETAILER_NOT_FOUND not in response.text
