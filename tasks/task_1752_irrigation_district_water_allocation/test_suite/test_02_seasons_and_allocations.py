"""Season lifecycle gates and allocation creation rules."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    assert_season,
    create_account,
    create_announced_season,
    create_season,
    create_season_payload,
    get_season,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestSeasonLifecycle:
    def test_open_draft_season_rejected(self, api):
        """PRD §3.1: "Attempting these transitions from a wrong from-state —
        opening a season still in `DRAFT`, for instance — is rejected with
        `ERR_INVALID_SEASON_STATE`."

        Design: Corner/state_machines/open_draft_season_rejected
        """
        season = create_season()
        assert season["status"] == "DRAFT"

        resp = api.open_season(season["id"], ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_SEASON_STATE)

        season_after = get_season(season["id"])
        assert season_after["status"] == "DRAFT", (
            "Rejected open must leave the season DRAFT"
        )

    def test_create_season_missing_required_year_returns_invalid_request(self, api):
        """PRD §2.7: "2. **Request shape** — required fields present, types
        valid, enum values within their declared sets, numbers positive where
        constrained, and end timestamps strictly after start timestamps, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/create_season_missing_required_year_returns_invalid_request
        """
        payload = create_season_payload()
        del payload["year"]
        resp = api.create_season(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

        _data, meta = validate_paginated(api.list_seasons(ADMIN))
        assert meta["total_count"] == 0, "No season may be persisted"

    def test_create_season_invalid_enum_returns_invalid_request(self, api):
        """PRD §3.1: "the `billing_method` (either `PER_ACRE` or
        `PER_AF_DELIVERED`)".
        PRD §2.7: "2. **Request shape** — required fields present, types valid,
        enum values within their declared sets, numbers positive where
        constrained, and end timestamps strictly after start timestamps, else
        `ERR_INVALID_REQUEST`."

        Design: Corner/validations/create_season_invalid_enum_returns_invalid_request
        """
        resp = api.create_season(
            create_season_payload(billing_method="PER_GALLON"), ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_duplicate_season_year_rejected(self, api):
        """PRD §3.1: "the calendar `year` (which must be unique across
        seasons — a duplicate year is refused with
        `ERR_DUPLICATE_SEASON_YEAR`)".

        Design: Corner/validations/duplicate_season_year_rejected
        """
        first = validate_success(api.create_season(create_season_payload(year=2026), ADMIN), expected_status=201)
        assert_season(first)

        resp = api.create_season(
            create_season_payload(
                year=2026,
                announced_af_per_acre=3.0,
                carryover_cap_pct=40,
                billing_method="PER_AF_DELIVERED",
                assessment_rate_per_acre=10.00,
                toll_tier1_cap_af=5.0,
                toll_tier1_rate_per_af=10.00,
                toll_tier2_rate_per_af=20.00,
                overage_rate_per_af=50.00,
            ),
            ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEASON_YEAR)

        _data, meta = validate_paginated(api.list_seasons(ADMIN))
        assert meta["total_count"] == 1, "Only one 2026 season may exist"


class TestAllocationCreation:
    def test_allocation_create_requires_announced_season(self, api):
        """PRD §3.1: "Once a season is `ANNOUNCED` or `OPEN`, the administrator
        may create a `SeasonAllocation` pairing a `water_account_id` with a
        `season_id`."
        PRD §2.7: "6. **Lifecycle state** — the target entity is in a valid
        from-state for the transition and cross-entity state gates hold
        (account `ACTIVE`, season `OPEN`, reach `IN_SERVICE`), else the
        appropriate `ERR_ACCOUNT_NOT_ACTIVE`, `ERR_SEASON_NOT_OPEN`, or
        `ERR_INVALID_*_STATE` code."

        Design: Corner/state_machines/allocation_create_requires_announced_season
        """
        season = create_season()  # stays DRAFT
        account = create_account(holder_name="Guard G", parcel_number="APN-104")

        resp = api.create_season_allocation(
            {"water_account_id": account["id"], "season_id": season["id"]}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_SEASON_NOT_OPEN)

        _data, meta = validate_paginated(
            api.list_season_allocations(ADMIN, params={"water_account_id": account["id"]})
        )
        assert meta["total_count"] == 0, "No SeasonAllocation may be persisted"

    def test_duplicate_allocation_rejected(self, api):
        """PRD §3.1: "Only one allocation may exist per account-season pair;
        a second attempt is refused with `ERR_DUPLICATE_ALLOCATION`."

        Design: Corner/validations/duplicate_allocation_rejected
        """
        season = create_announced_season()
        account = create_account(holder_name="Dup D", parcel_number="APN-127")
        first = validate_success(
            api.create_season_allocation(
                {"water_account_id": account["id"], "season_id": season["id"]}, ADMIN,
            ),
            expected_status=201,
        )
        assert first["status"] == "ACTIVE"

        resp = api.create_season_allocation(
            {"water_account_id": account["id"], "season_id": season["id"]}, ADMIN,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_ALLOCATION)
