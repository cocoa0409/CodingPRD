"""Subscriber signup, subscriber reads, response envelope, empty impact report.

Covers PRD §2.1 (roles), §2.2 (response envelope), §2.10 (validation order),
§3.1 (signup defaults), §3.8 (impact report over an empty history).
"""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_subscriber,
    create_subscriber,
    create_subscriber_payload,
    get_subscriber,
    is_iso8601_timestamp,
    is_valid_uuid,
    make_subscriber_headers,
    validate_error,
    validate_success,
)


class TestSubscriberDefaults:
    def test_fresh_subscriber_applies_defaults(self, api, ops_headers):
        """PRD §3.1: "A fresh subscriber begins in `GOOD_STANDING` with a
        `credit_balance_cents` of zero."

        Design: Corner/entities/create_subscriber_applies_defaults
        """
        created = create_subscriber()
        data = validate_success(api.get_subscriber(created["id"], ops_headers))
        assert_subscriber(data)
        assert data["account_standing"] == "GOOD_STANDING"
        assert data["credit_balance_cents"] == 0
        assert isinstance(data["version"], int) and data["version"] >= 1

    def test_subscriber_invalid_enum_rejected(self, api, anonymous_headers):
        """PRD §2.10: "Third, request-body shape: required fields present, enums
        valid, ranges valid — `fullness_pct` between zero and one inclusive,
        `bags` at least one, `pause_end` later than `pause_start`,
        `week_start_date` a Monday, an adjustment's `amount_cents` nonzero —
        otherwise `ERR_INVALID_REQUEST`."
        PRD §3.1: "supplying an `email`, a `full_name`, a `subscriber_type` of
        `RESIDENTIAL` or `COMMERCIAL`, and a service `address`."

        Design: Corner/entities/create_subscriber_invalid_enum_returns_invalid_request
        """
        resp = api.create_subscriber(
            create_subscriber_payload(subscriber_type="HOUSEHOLD"), anonymous_headers
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_system_fields_on_create_are_ignored(self, api, anonymous_headers):
        """PRD §2.5: "The `id` is a server-minted UUID with no type prefix."
        PRD §3.1: "A fresh subscriber begins in `GOOD_STANDING` with a
        `credit_balance_cents` of zero."

        Design: Corner/entities/create_subscriber_system_fields_input_ignored
        """
        supplied_id = "11111111-1111-4111-8111-111111111111"
        data = validate_success(
            api.create_subscriber(
                create_subscriber_payload(
                    id=supplied_id, version=99, credit_balance_cents=777
                ),
                anonymous_headers,
            ),
            201,
        )
        assert is_valid_uuid(data["id"])
        assert data["id"] != supplied_id, "server mints its own id"
        assert data["credit_balance_cents"] == 0
        assert data["account_standing"] == "GOOD_STANDING"

    def test_unknown_subscriber_returns_not_found(self, api, ops_headers):
        """PRD §2.10: "Fourth, existence: every identifier referenced in the
        path and body — `plan_id`, `route_id`, `subscriber_id`, `new_plan_id`,
        and any path `id` — must resolve to an existing entity, otherwise
        `ERR_NOT_FOUND`; path identifiers are resolved left to right as they
        appear in the URL, and the first unresolvable identifier produces the
        404."

        Design: Corner/entities/get_unknown_subscriber_returns_not_found
        """
        resp = api.get_subscriber(NON_EXISTENT_UUID, ops_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestResponseEnvelope:
    def test_envelope_shape_on_success_and_error(self, api, anonymous_headers, ops_headers):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`."
        PRD §2.2: "The `error_id` is a unique, machine-readable string that
        identifies the specific error."

        Design: Corner/endpoints/response_envelope_shape_on_success_and_error
        """
        ok = api.create_subscriber(create_subscriber_payload(), anonymous_headers)
        assert ok.status_code == 201
        body = ok.json()
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert body["response_type"] == "object"
        assert body["data"]["id"]

        err = api.get_subscriber(NON_EXISTENT_UUID, ops_headers)
        err_body = err.json()
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_NOT_FOUND"
        assert err_body["data"]["message"].strip()


class TestImpactReportEmpty:
    def test_impact_report_zero_for_new_subscriber(self, api):
        """PRD §3.8: "The report also counts `pickups_completed` — the number of
        those completed pickups — and `contamination_tags_confirmed`, the number
        of the subscriber's tags standing in `CONFIRMED`."
        PRD §3.8: "The report's `total_kg_diverted` is the sum of those kilograms
        rounded half-up to two decimal places" — over no pickups the sums are 0.

        Design: Corner/endpoints/impact_report_zero_for_new_subscriber
        """
        sub = create_subscriber()
        data = validate_success(
            api.get_impact(sub["id"], make_subscriber_headers(sub["id"]))
        )
        assert data["total_kg_diverted"] == 0.0
        assert data["total_co2e_kg"] == 0.0
        assert data["pickups_completed"] == 0
        assert data["contamination_tags_confirmed"] == 0


class TestImpactReportAggregation:
    def test_impact_aggregates_completed_pickups_and_confirmed_tags(self, api):
        """PRD §3.8: "Across all `COMPLETED` pickups of the subscriber's
        subscriptions, each pickup contributes its `final_kg` once weighed and
        its `estimated_kg` otherwise. The report's `total_kg_diverted` is the
        sum of those kilograms rounded half-up to two decimal places, and
        `total_co2e_kg` is that total multiplied by one half kilogram of
        CO2-equivalent per diverted kilogram, again rounded half-up to two
        decimal places. The report also counts `pickups_completed` — the number
        of those completed pickups — and `contamination_tags_confirmed`, the
        number of the subscriber's tags standing in `CONFIRMED`."

        Design: Corner/calculations/impact_report_aggregates_completed_pickups_and_confirmed_tags
        """
        import pytest

        from test_helpers import (
            complete_pickup,
            confirm_tag,
            generate_and_get_pickups,
            setup_active_subscription,
            tag_pickup,
            waive_tag,
        )

        env = setup_active_subscription(bin_count=3)
        sub_id = env["subscription"]["id"]
        pickups = generate_and_get_pickups(
            env["route"]["id"], sub_id, ["2026-06-01", "2026-06-08"]
        )
        complete_pickup(pickups[0]["id"], 0.5)  # 10.00 kg estimated, unweighed
        complete_pickup(pickups[1]["id"], 0.5)
        tag1 = tag_pickup(pickups[0]["id"], severity="LOW", category="PLASTIC")
        confirm_tag(tag1["id"])
        tag2 = tag_pickup(pickups[1]["id"], severity="LOW", category="GLASS")
        waive_tag(tag2["id"])  # waived tags do not count

        data = validate_success(
            api.get_impact(env["subscriber"]["id"], make_subscriber_headers(env["subscriber"]["id"]))
        )
        assert data["total_kg_diverted"] == pytest.approx(20.0)
        assert data["total_co2e_kg"] == pytest.approx(10.0)  # 20.0 x 0.5
        assert data["pickups_completed"] == 2
        assert data["contamination_tags_confirmed"] == 1


class TestAnonymousAccess:
    def test_anonymous_cannot_read_subscriber(self, api, anonymous_headers):
        """PRD §2.1: "A request whose role is not listed on the target endpoint —
        or, for a `Subscriber` caller, one that targets a resource the caller does
        not own — is rejected with `ERR_FORBIDDEN_ROLE`."
        PRD §4: GET /subscribers/{id} is listed for Subscriber and
        OperationsManager only.

        Design: Corner/rbac/anonymous_cannot_read_subscriber_forbidden
        """
        sub = create_subscriber()
        resp = api.get_subscriber(sub["id"], anonymous_headers)
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_ROLE)
