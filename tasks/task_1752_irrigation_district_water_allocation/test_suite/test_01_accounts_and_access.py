"""Water account onboarding, account closure gate, and role/access checks."""
from test_helpers import (
    ADMIN,
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_water_account,
    create_account,
    get_account,
    make_water_user_headers,
    place_order,
    setup_open_season_with_allocation,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAccountCreation:
    def test_water_account_creation_defaults(self, api):
        """PRD §3.1: "The account is born `ACTIVE`, its `priority_class` is
        derived from the priority date per §2.9, and it immediately
        participates in every ownership check that `WaterUser` callers will
        later face."
        PRD §2.9: "An account whose `water_right_priority_date` falls on or
        before 1914-12-31 is classed `SENIOR`; any later date is classed
        `JUNIOR`."
        PRD §2.4: "Every persisted resource carries an `id` (a server-minted
        UUID with no type prefix), a `created_at` timestamp, an `updated_at`
        timestamp, and a `version` integer."

        Design: Corner/entities/water_account_creation_defaults
        """
        resp = api.create_water_account(
            {
                "holder_name": "New N",
                "parcel_number": "APN-100",
                "irrigated_acres": 12.5,
                "water_right_priority_date": "1888-03-10T00:00:00Z",
            },
            ADMIN,
        )
        data = validate_success(resp, expected_status=201)
        assert_water_account(data)
        assert data["status"] == "ACTIVE", "New account must be born ACTIVE"
        assert data["priority_class"] == "SENIOR", (
            "1888-03-10 is on or before the 1914-12-31 cut date"
        )
        assert isinstance(data["version"], int), "version must be an integer"

    def test_priority_class_cut_date_boundary(self, api):
        """PRD §2.9: "An account whose `water_right_priority_date` falls on or
        before 1914-12-31 is classed `SENIOR`; any later date is classed
        `JUNIOR`."

        Design: Corner/entities/priority_class_cut_date_boundary
        """
        on_cut = validate_success(
            api.create_water_account(
                {
                    "holder_name": "Cut C",
                    "parcel_number": "APN-101",
                    "irrigated_acres": 1.0,
                    "water_right_priority_date": "1914-12-31T00:00:00Z",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        after_cut = validate_success(
            api.create_water_account(
                {
                    "holder_name": "Next N",
                    "parcel_number": "APN-102",
                    "irrigated_acres": 1.0,
                    "water_right_priority_date": "1915-01-01T00:00:00Z",
                },
                ADMIN,
            ),
            expected_status=201,
        )
        assert on_cut["priority_class"] == "SENIOR", (
            "1914-12-31 is the inclusive SENIOR boundary"
        )
        assert after_cut["priority_class"] == "JUNIOR", (
            "1915-01-01 is later than the cut date"
        )

    def test_get_water_account_not_found_returns_404(self, api):
        """PRD §2.7: "4. **Existence** — referenced resources exist, path
        identifiers checked left-to-right first, then body foreign-key fields
        in their declared input order, else `ERR_NOT_FOUND`."

        Design: Corner/entities/get_water_account_not_found_returns_404
        """
        resp = api.get_water_account(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)

    def test_create_account_nonpositive_acres_returns_invalid_request(self, api):
        """PRD §3.1: an account is created with "the `irrigated_acres` under
        irrigation (which must be greater than zero)".
        PRD §2.7: "2. **Request shape** — required fields present, types valid,
        enum values within their declared sets, numbers positive where
        constrained, and end timestamps strictly after start timestamps, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/create_account_nonpositive_acres_returns_invalid_request
        """
        resp = api.create_water_account(
            {
                "holder_name": "Zero Z",
                "parcel_number": "APN-125",
                "irrigated_acres": 0,
                "water_right_priority_date": "1888-01-01T00:00:00Z",
            },
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAccountCloseGate:
    def test_close_account_with_open_order_rejected(self, api):
        """PRD §3.9: "Closure is refused with `ERR_INVALID_ACCOUNT_STATE`
        while the account has any turnout order in `REQUESTED`, `SCHEDULED`,
        or `FLOWING`, or any transfer request in `PENDING` or `APPROVED`."

        Design: Corner/state_machines/close_account_with_open_order_rejected
        """
        scenario = setup_open_season_with_allocation(
            holder_name="Hold H", parcel_number="APN-113",
        )
        account = scenario["account"]
        place_order(
            account["id"], scenario["allocation"]["id"], scenario["reach"]["id"],
        )

        resp = api.close_water_account(account["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_ACCOUNT_STATE)

        account_after = get_account(account["id"])
        assert account_after["status"] == "ACTIVE", (
            "Rejected close must leave the account ACTIVE"
        )


class TestAccessControl:
    def test_missing_auth_header_returns_unauthenticated(self, api):
        """PRD §2.1: "A request missing either header, or presenting a role
        string outside this set, is rejected with `ERR_UNAUTHENTICATED`
        (HTTP 401)."

        Design: Corner/rbac/missing_auth_header_returns_unauthenticated
        """
        resp = api.list_water_accounts(headers={})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)

    def test_wateruser_cannot_create_season_forbidden(self, api):
        """PRD §2.1: "A request whose role is not permitted for the endpoint,
        or whose ownership check fails, is rejected with `ERR_FORBIDDEN`
        (HTTP 403)."
        PRD §4: POST /district/seasons is authorized for DistrictAdmin only.

        Design: Corner/rbac/wateruser_cannot_create_season_forbidden
        """
        account = create_account(holder_name="Role R", parcel_number="APN-136")
        season_payload = {
            "year": 2026,
            "announced_af_per_acre": 2.0,
            "carryover_cap_pct": 50,
            "billing_method": "PER_ACRE",
            "assessment_rate_per_acre": 25.00,
            "toll_tier1_cap_af": 20.0,
            "toll_tier1_rate_per_af": 18.00,
            "toll_tier2_rate_per_af": 30.00,
            "overage_rate_per_af": 60.00,
            "start_date": "2026-04-01T00:00:00Z",
            "end_date": "2026-09-30T00:00:00Z",
        }
        resp = api.create_season(
            season_payload, make_water_user_headers(account["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN)

        _data, meta = validate_paginated(api.list_seasons(ADMIN))
        assert meta["total_count"] == 0, (
            "No season may be persisted by the forbidden call"
        )
