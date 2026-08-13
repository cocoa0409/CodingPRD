"""Dealer onboarding, persisted/computed fields, dealer OCC, and the
paginated dealer list (PRD §3.2, §2.3, §2.7)."""
import pytest

from test_helpers import (
    ApiErrorId,
    NON_EXISTENT_UUID,
    TEST_USERS,
    assert_dealer,
    create_dealer,
    create_dealer_payload,
    create_update_dealer_payload,
    get_dealer,
    validate_error,
    validate_paginated,
    validate_success,
)

ALLOC = TEST_USERS["allocation_manager_headers"]
ANY = TEST_USERS["any_headers"]


class TestDealerOnboarding:
    def test_dealer_creation_computed_fields_initialized(self, api):
        """PRD §3.2: "Onboarding zeroes the computed fields: `allocation_used`
        starts at 0, `floor_plan_utilized_cents` at 0, and `current_rate_tier`
        at `TIER_STANDARD`."
        PRD §3.2: "The dealer's `standing` may be supplied as `PREFERRED`,
        `STANDARD`, or `PROBATION` and defaults to `STANDARD`."

        Design: Corner/entities/dealer_creation_computed_fields_initialized
        """
        data = validate_success(
            api.create_dealer(
                create_dealer_payload(dealer_code="D-100"), ALLOC
            ),
            201,
        )
        assert_dealer(data)
        assert data["allocation_used"] == 0
        assert data["floor_plan_utilized_cents"] == 0
        assert data["current_rate_tier"] == "TIER_STANDARD"
        assert data["standing"] == "STANDARD", "standing must default to STANDARD"

    def test_dealer_get_by_id_returns_persisted_fields(self, api):
        """PRD §3.2: "An `AllocationManager` onboards each dealership with a
        unique `dealer_code`, a `name`, a sales `region` code such as SE or NW,
        an `annual_allocation_quota` of zero or more, and a
        `floor_plan_limit_cents` strictly greater than zero."
        PRD §2.2: "Unless otherwise noted, operations that create or modify a
        resource will return the created or updated resource object in the data
        field."

        Design: Corner/entities/dealer_get_by_id_returns_persisted_fields
        """
        created = create_dealer(
            api,
            dealer_code="D-100",
            name="Coastal Marine",
            annual_allocation_quota=5,
            floor_plan_limit_cents=10000000,
        )
        got = validate_success(api.get_dealer(created["id"], ANY), 200)
        assert_dealer(got)
        assert got["dealer_code"] == "D-100"
        assert got["annual_allocation_quota"] == 5
        assert got["floor_plan_limit_cents"] == 10000000

    def test_dealer_get_not_found(self, api):
        """PRD §2.9: "Path identifiers exist, validated left to right along the
        URL — the first missing resource yields its `ERR_{RESOURCE}_NOT_FOUND`:
        `ERR_DEALER_NOT_FOUND`, `ERR_ORDER_NOT_FOUND`, `ERR_HULL_NOT_FOUND`,
        `ERR_CLAIM_NOT_FOUND`, `ERR_CAMPAIGN_NOT_FOUND`, `ERR_NOTICE_NOT_FOUND`,
        `ERR_RUN_NOT_FOUND`, or `ERR_MODEL_NOT_FOUND`."

        Design: Corner/entities/dealer_get_not_found
        """
        resp = api.get_dealer(NON_EXISTENT_UUID, ANY)
        validate_error(resp, ApiErrorId.ERR_DEALER_NOT_FOUND)


class TestDealerOcc:
    def test_dealer_patch_succeeds_with_correct_version(self, api):
        """PRD §3.2: "The allocation desk may later revise a dealer's
        `annual_allocation_quota`, `floor_plan_limit_cents`, or `standing`; such
        an update must carry `expected_dealer_version`, increments the dealer's
        `version` by one, and re-derives `current_rate_tier` whenever the limit
        changes."

        Design: Corner/cross_cutting_layers/occ_dealer_patch_succeeds_with_correct_version
        """
        dealer = create_dealer(api, dealer_code="D-1")
        before = dealer["version"]
        updated = validate_success(
            api.update_dealer(
                dealer["id"],
                create_update_dealer_payload(before, annual_allocation_quota=10),
                ALLOC,
            ),
            200,
        )
        assert_dealer(updated)
        assert updated["annual_allocation_quota"] == 10
        assert updated["version"] == before + 1, (
            f"version must increment by one: {before} -> {updated['version']}"
        )

    def test_dealer_patch_stale_version_returns_412(self, api):
        """PRD §2.7: "Updating a dealer's quota, floor-plan limit, or standing
        (`PATCH /dealers/{id}`) requires a non-optional `expected_dealer_version`.
        A mismatch with the dealer's current `version` is rejected with
        `ERR_STALE_DEALER_VERSION` (HTTP 412), so quota and limit changes are
        never based on superseded utilization state."

        Design: Corner/validations/occ_stale_dealer_version_on_patch_returns_412
        """
        dealer = create_dealer(api, dealer_code="D-1")
        v1 = dealer["version"]
        updated = validate_success(
            api.update_dealer(
                dealer["id"],
                create_update_dealer_payload(v1, annual_allocation_quota=10),
                ALLOC,
            ),
            200,
        )
        assert updated["version"] == v1 + 1
        resp = api.update_dealer(
            dealer["id"],
            create_update_dealer_payload(updated["version"] - 1, annual_allocation_quota=20),
            ALLOC,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_DEALER_VERSION)


class TestDealerListPagination:
    def test_dealers_list_pagination_envelope(self, api):
        """PRD §2.3: "`limit` caps the number of items returned: it defaults to
        10, with a minimum of 1 and a maximum of 100. `offset` is the number of
        items to skip and defaults to 0. Unless otherwise specified, every list
        endpoint returns its resources sorted by creation timestamp in ascending
        order. The `meta` object of a list response carries the pagination
        fields `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/get_dealers_list_pagination_envelope
        """
        for code in ("D-1", "D-2", "D-3"):
            create_dealer(api, dealer_code=code)
        resp = api.list_dealers(ANY, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert len(data) == 2, f"limit=2 must cap the page, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True, "offset 0 + limit 2 < total 3 -> has_more"
        assert meta["limit"] == 2
        assert meta["offset"] == 0
        for row in data:
            assert_dealer(row)
