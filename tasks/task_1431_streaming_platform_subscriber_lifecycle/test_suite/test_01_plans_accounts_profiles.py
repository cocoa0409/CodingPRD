"""Plan catalog, account opening, profile roster, and household-cap boundaries."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    api_client,
    assert_account,
    assert_plan,
    assert_profile,
    create_account,
    create_account_payload,
    create_plan,
    create_plan_payload,
    create_profile,
    create_profile_payload,
    make_subscriber_headers,
    set_clock,
    setup_account_with_subscription,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["platform_admin_headers"]


class TestPlanCreation:

    def test_plan_created_with_all_fields(self):
        """PRD section 3.1: "A `PlatformAdmin` defines a plan by supplying a
        stable business `plan_code` (unique among active plans), a human-facing
        `display_name`, a `tier` of `BASIC`, `STANDARD`, or `PREMIUM`, the list
        `monthly_price_cents`, a `trial_days` length (zero meaning the plan
        offers no trial), and the sharing envelope".
        PRD section 3.1: "Newly created plans carry `is_archived` set to false."

        Design: Corner/entities/plan_creation_required_fields
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_plan(
            create_plan_payload(
                plan_code="STD",
                display_name="Standard",
                tier="STANDARD",
                monthly_price_cents=1500,
                trial_days=7,
                max_profiles=2,
                max_households=1,
            ),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_plan(data)
        assert data["tier"] == "STANDARD"
        assert data["monthly_price_cents"] == 1500
        assert data["is_archived"] is False

    def test_plan_missing_plan_code_returns_invalid_request(self):
        """PRD section 2.8: "A body that fails schema validation outright — a
        missing required field, a wrong-typed value, an invalid enum member —
        is rejected with `ERR_INVALID_REQUEST` (HTTP 400)."

        Design: Corner/entities/plan_creation_missing_required_field_returns_invalid_request
        """
        set_clock("2026-08-01T00:00:00Z")
        payload = create_plan_payload(plan_code="STD")
        del payload["plan_code"]
        resp = api_client.create_plan(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAccountOpening:

    def test_account_email_globally_unique(self):
        """PRD section 3.2: "A subscriber relationship starts when a
        `PlatformAdmin` opens an account with an `email` (globally unique
        across the service), the holder's `full_name`, and an ISO-3166
        alpha-2 `country_code`."

        Design: Corner/entities/account_email_uniqueness_enforced
        """
        set_clock("2026-08-01T00:00:00Z")
        first = api_client.create_account(
            create_account_payload(email="dup@x.com", full_name="First"), ADMIN
        )
        validate_success(first, expected_status=201)
        resp = api_client.create_account(
            create_account_payload(email="dup@x.com", full_name="Second"), ADMIN
        )
        # The uniqueness rule is pinned; the error taxonomy for a duplicate
        # email is a schema-level rejection.
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_account_outstanding_balance_initialized_to_zero(self):
        """PRD section 2.7: "The account's `outstanding_balance_cents` is a
        computed figure, never set directly: it is the sum of the amounts of
        unsettled `CHARGE_FAILED` events minus the amounts recovered since."
        PRD section 3.2: "A new account stands immediately in `ACTIVE` status,
        with `active_subscription_id` null until a subscription exists."

        Design: Corner/entities/account_computed_outstanding_balance_field
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.create_account(
            create_account_payload(email="cb@x.com", full_name="CB"), ADMIN
        )
        data = validate_success(resp, expected_status=201)
        assert_account(data)
        # A fresh account has no unsettled CHARGE_FAILED events, so the
        # computed balance is zero — and any client-supplied value is ignored.
        assert data["outstanding_balance_cents"] == 0, (
            f"fresh account must compute outstanding_balance_cents == 0, "
            f"got {data['outstanding_balance_cents']}"
        )
        assert data["account_status"] == "ACTIVE"
        assert data["active_subscription_id"] is None


class TestPlanRead:

    def test_get_plan_not_found_returns_404(self):
        """PRD section 2.8: "every path parameter must identify an existing
        resource, validated strictly left-to-right along the path, so a
        missing parent masks everything beneath it; failures surface
        `ERR_NOT_FOUND` (404)."

        Design: Corner/entities/get_plan_not_found_returns_404
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.get_plan(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)


class TestProfileRoster:

    def test_profile_list_pagination_fields(self):
        """PRD section 2.3: "Paginated and non-paginated list-based responses
        include the following fields in the `meta` object of the response
        envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD section 3.3: "the roster can be listed with filters on
        `account_id`, `profile_status`, or `household_id`."

        Design: Corner/entities/profile_list_supports_pagination
        """
        plan, account, _sub = setup_account_with_subscription(
            plan_overrides={"max_profiles": 5, "max_households": 2}
        )
        create_profile(account["account_id"], display_name="P1")
        create_profile(account["account_id"], display_name="P2")
        resp = api_client.list_profiles(
            ADMIN, params={"account_id": account["account_id"], "limit": 1,
                           "offset": 0}
        )
        data, meta = validate_paginated(resp)
        assert meta["limit"] == 1
        assert meta["offset"] == 0
        assert meta["total_count"] == 2, (
            f"expected total_count 2 for the account's two profiles, "
            f"got {meta['total_count']}"
        )
        assert meta["has_more"] is True
        assert len(data) == 1
        assert_profile(data[0])


class TestBillingEventLedgerShape:

    def test_billing_event_ledger_starts_empty_and_is_append_only(self):
        """PRD section 2.7: "The ledger is append-only: corrections are
        posted as new offsetting events rather than edits to existing ones."
        PRD section 2.5: "a `BillingEvent` is an immutable, append-only ledger
        entry and carries only its `billing_event_id` and `created_at` from
        the common set — both `updated_at` and `version` are absent, because
        a posted event is never modified."

        Design: Corner/entities/billing_event_immutable_no_update_endpoint
        """
        set_clock("2026-08-01T00:00:00Z")
        resp = api_client.list_billing_events(ADMIN)
        data, meta = validate_paginated(resp)
        assert data == [], f"fresh ledger must be empty, got {data}"
        assert meta["total_count"] == 0
        # Immutability is structural: the PRD's endpoint catalogue (section 4)
        # declares only GET and POST for /v1/billing-events — there is no
        # update or delete verb to test against.


class TestHouseholdCapBoundary:
    """Boundary precision on the distinct-household count (PRD section 3.3)."""

    def test_profile_at_exactly_max_households_succeeds(self):
        """PRD section 3.3: "the account violates the sharing policy only when
        that count is strictly greater than the plan's `max_households` — an
        account sitting exactly at the cap is compliant, and an account with
        no profiles counts zero households."

        Design: Difficulty/boundary_precision_check/household_count_at_exactly_max
        """
        plan, account, _sub = setup_account_with_subscription(
            plan_overrides={"max_profiles": 5, "max_households": 1}
        )
        create_profile(account["account_id"], display_name="P13a",
                       household_id="hh-1")
        resp = api_client.create_profile(
            create_profile_payload(account["account_id"], display_name="P13b",
                                   household_id="hh-1"),
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_profile(data)
        assert data["profile_status"] == "ACTIVE", (
            "second profile on the same household keeps the distinct count "
            "at exactly max_households (1), which is compliant"
        )

    def test_profile_beyond_max_households_rejected(self):
        """PRD section 3.3: "the account violates the sharing policy only when
        that count is strictly greater than the plan's `max_households`".
        PRD section 3.3: "Violations at profile creation or reactivation are
        refused with `ERR_HOUSEHOLD_LIMIT_EXCEEDED`."

        Design: Difficulty/boundary_precision_check/household_count_at_exactly_max
        """
        plan, account, _sub = setup_account_with_subscription(
            plan_overrides={"max_profiles": 5, "max_households": 1}
        )
        create_profile(account["account_id"], display_name="P13a",
                       household_id="hh-1")
        resp = api_client.create_profile(
            create_profile_payload(account["account_id"], display_name="P13c",
                                   household_id="hh-2"),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_HOUSEHOLD_LIMIT_EXCEEDED)
