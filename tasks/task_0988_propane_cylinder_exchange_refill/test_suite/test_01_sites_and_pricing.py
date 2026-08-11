"""Host site onboarding/configuration and pricing policy windows (PRD §2.3, §2.6, §3.1)."""
import pytest

from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    add_policy,
    advance_clock,
    assert_host_site,
    confirm_leak,
    create_priced_site,
    create_site,
    create_site_payload,
    get_site,
    get_site_version,
    open_session,
    register_customer_cylinder,
    register_fleet_cylinders,
    report_leak,
    swap_completed,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
CLERK1 = TEST_USERS["site_clerk_headers"]


class TestSiteCreation:
    def test_site_creation_applies_defaults(self, api):
        """PRD §3.1: "Financial defaults round out the record: `address` defaults to empty, `opening_float_cents` — the declared cash drawer float — defaults to 20,000 cents, `hazmat_fee_cents` defaults to zero, and `promo_waives_hazmat` defaults to false."
        PRD §3.1: "A new site begins `ACTIVE`, with all three cage counts at zero and `sales_posture` `SALES_OPEN`."
        PRD §2.8: "`reorder_floor_full` is the site's `par_level_full` multiplied by one-half and rounded up to a whole cylinder, and `restock_alert` is true exactly when `full_on_hand` is less than or equal to `reorder_floor_full` — the threshold is inclusive."
        PRD §2.4: "`version` (integer): a system-managed integer that starts at 1 and increments by exactly one on every mutation of that row, including mutations driven by cascades."

        Design: Corner/entities/site_creation_applies_defaults
        """
        res = api.create_site(create_site_payload(name="Default Site"), ADMIN)
        site = validate_success(res, 201)
        assert_host_site(site)
        assert site["status"] == "ACTIVE"
        assert site["sales_posture"] == "SALES_OPEN"
        assert site["version"] == 1
        assert site["opening_float_cents"] == 20000
        assert site["commission_basis"] == "GROSS"
        assert site["recon_basis"] == "BOOK"
        assert site["hazmat_fee_cents"] == 0
        assert site["promo_waives_hazmat"] is False
        assert site["full_on_hand"] == 0
        assert site["empty_on_hand"] == 0
        assert site["quarantined_on_hand"] == 0
        assert site["reorder_floor_full"] == 6, "ceil(12 * 0.5) == 6"
        assert site["restock_alert"] is True, "0 <= 6, inclusive threshold"

    def test_get_missing_site_not_found(self, api):
        """PRD §2.7 (stage 3): "Resource identifiers appearing in the URL path exist, validated left to right, so the first missing identifier in the path is the one reported; otherwise `ERR_NOT_FOUND`."

        Design: Corner/entities/get_missing_site_not_found
        """
        res = api.get_site(NON_EXISTENT_UUID, ADMIN)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND, expected_status=404)

    def test_create_site_missing_required_field(self, api):
        """PRD §3.1: "The commission configuration is captured up front as well: `commission_rate_bps`, between zero and three thousand basis points" — unlike its siblings it carries no default, so omitting it is a malformed request.
        PRD §5: `ERR_VALIDATION` | 400 Bad Request.

        Design: Corner/entities/create_site_missing_required_field
        """
        payload = {"name": "Bad Site", "cage_capacity_cylinders": 20, "par_level_full": 12}
        res = api.create_site(payload, ADMIN)
        validate_error(res, ApiErrorId.ERR_VALIDATION, expected_status=400)

    def test_host_site_cage_counts_computed(self, api):
        """PRD §2.8: "Every host site exposes three live cage counts, computed on read rather than stored."
        PRD §2.8: "Because the counts are computed, any cylinder mutation touching `current_site_id`, `in_transit_run_id`, `fill_status`, `cert_status`, or `owner_kind` re-derives them — cylinder registration itself never mutates the site row."

        Design: Corner/entities/host_site_cage_counts_computed
        """
        site = create_site(name="Count Site")
        register_fleet_cylinders(site_id=site["id"], count=2, fill="FULL", serial_prefix="C")
        register_fleet_cylinders(site_id=site["id"], count=1, fill="EMPTY", serial_prefix="C")
        read = get_site(site["id"])
        assert read["full_on_hand"] == 2
        assert read["empty_on_hand"] == 1
        assert read["quarantined_on_hand"] == 0


class TestSiteStatusGates:
    def test_sales_at_suspended_site_rejected(self, api):
        """PRD §3.1: "Sales and dispatch operations at a site that is not `ACTIVE` are refused with `ERR_SITE_NOT_ACTIVE`."

        Design: Corner/validations/sales_at_suspended_site_rejected
        """
        site, _policy = create_priced_site()
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="SS")
        version = get_site_version(site["id"])
        validate_success(
            api.patch_site(site["id"], {"expected_site_version": version, "status": "SUSPENDED"}, ADMIN),
            200,
        )
        res = api.create_exchange_order({"site_id": site["id"]}, CLERK1)
        validate_error(res, ApiErrorId.ERR_SITE_NOT_ACTIVE, expected_status=409)

    def test_decommission_with_stock_rejected(self, api):
        """PRD §3.1: "the site may transition to `DECOMMISSIONED` only when the cage is completely empty — `full_on_hand`, `empty_on_hand`, and `quarantined_on_hand` all zero — and when no restock run for the site sits in `DRAFT`, `DISPATCHED`, `IN_PROGRESS`, or `COMPLETED`; a run already `VERIFIED` or `CANCELLED` does not block. Violating either condition is rejected with `ERR_SITE_NOT_EMPTY`."

        Design: Corner/validations/decommission_with_stock_rejected
        """
        site = create_site(name="Doomed Site")
        register_fleet_cylinders(site_id=site["id"], count=1, fill="FULL", serial_prefix="DX")
        v1 = get_site_version(site["id"])
        suspended = validate_success(
            api.patch_site(site["id"], {"expected_site_version": v1, "status": "SUSPENDED"}, ADMIN),
            200,
        )
        res = api.patch_site(
            site["id"],
            {"expected_site_version": suspended["version"], "status": "DECOMMISSIONED"},
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_SITE_NOT_EMPTY, expected_status=409)


class TestSiteListing:
    def test_list_sites_pagination_defaults(self, api):
        """PRD §2.3: "Paginated and non-paginated list-based responses include the following fields in the `meta` object of the response envelope: `limit`, `offset`, `total_count`, and `has_more`."
        PRD §2.3: "The `limit` parameter specifies the maximum number of items to return."

        Design: Corner/endpoints/list_sites_pagination_defaults
        """
        for name in ("S1", "S2", "S3"):
            create_site(name=name)
        page1, meta1 = validate_paginated(api.list_sites(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True
        page2, meta2 = validate_paginated(api.list_sites(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False


class TestOptimisticConcurrency:
    def test_occ_site_patch_stale_version(self, api):
        """PRD §2.6: "If the value does not match the site's current `version` — because another accepted write has advanced the site since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §2.6: "All three guarded writes themselves advance the host site's `version` by one when they succeed, alongside refreshing `updated_at`."

        Design: Corner/cross_cutting_layers/occ_site_patch_stale_version
        """
        site = create_site(name="OCC Patch Site")
        assert site["version"] == 1
        patched = validate_success(
            api.patch_site(site["id"], {"expected_site_version": 1, "par_level_full": 10}, ADMIN),
            200,
        )
        assert patched["version"] == 2
        res = api.patch_site(site["id"], {"expected_site_version": 1, "par_level_full": 8}, ADMIN)
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_occ_pricing_policy_create_stale_version(self, api):
        """PRD §2.6: "Three write operations are guarded by optimistic concurrency control against the host site's `version`: creating a restock run, creating a pricing policy, and patching a site's configuration or status."
        PRD §2.6: "If the value does not match the site's current `version` — because another accepted write has advanced the site since the client last read it — the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_layers/occ_pricing_policy_create_stale_version
        """
        site = create_site(name="OCC Policy Site")
        add_policy(site["id"])  # bumps site version 1 -> 2
        res = api.create_pricing_policy(
            {
                "site_id": site["id"],
                "expected_site_version": 1,  # stale
                "swap_price_cents": 2599,
                "core_deposit_cents": 3500,
                "tax_rate_bps": 825,
                "refill_tier1_cents_per_lb": 349,
                "refill_tier1_max_lbs": 15.00,
                "refill_tier2_cents_per_lb": 299,
                "effective_from": "2026-06-01",
                "supersede_current": True,
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


class TestPricingPolicyWindows:
    def test_policy_past_and_overlapping_reports_temporal_error(self, api):
        """PRD §2.7: "Incoming requests are validated against a fixed, fourteen-stage evaluation order; the first stage that fails determines the rejection, and later stages are not consulted."
        PRD §2.7 (stage 10): "A new pricing policy's window may not begin in the past (`ERR_POLICY_WINDOW_IN_PAST`), and a commission period must be fully closed before finalization (`ERR_PERIOD_NOT_CLOSED`)."
        PRD §3.1: "The new `effective_from` may not be strictly before the current logical date, else `ERR_POLICY_WINDOW_IN_PAST`."

        Design: Difficulty/priority_pair_validation_conflict/policy_past_window_temporal_beats_overlap
        """
        site, _p1 = create_priced_site()  # P1 effective 2026-05-01, open-ended
        version = get_site_version(site["id"])
        res = api.create_pricing_policy(
            {
                "site_id": site["id"],
                "expected_site_version": version,
                "swap_price_cents": 2199,
                "core_deposit_cents": 3500,
                "tax_rate_bps": 825,
                "refill_tier1_cents_per_lb": 349,
                "refill_tier1_max_lbs": 15.00,
                "refill_tier2_cents_per_lb": 299,
                # 2026-04-01 is both in the past AND overlapping P1; stage 10 fires first.
                "effective_from": "2026-04-01",
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_WINDOW_IN_PAST, expected_status=422)

    def test_policy_past_window_rejected_even_without_overlap(self, api):
        """PRD §3.1: "The new `effective_from` may not be strictly before the current logical date, else `ERR_POLICY_WINDOW_IN_PAST`."
        The logical clock starts at exactly 2026-05-01 (PRD §2.4: "At startup — before any operator action — the logical clock reads exactly `2026-05-01T00:00:00Z`").

        Design: Difficulty/priority_pair_validation_conflict/policy_past_window_temporal_beats_overlap
        """
        site = create_site(name="Past Window Site")  # no policy at all -> no overlap possible
        res = api.create_pricing_policy(
            {
                "site_id": site["id"],
                "expected_site_version": site["version"],
                "swap_price_cents": 2499,
                "core_deposit_cents": 3500,
                "tax_rate_bps": 825,
                "refill_tier1_cents_per_lb": 349,
                "refill_tier1_max_lbs": 15.00,
                "refill_tier2_cents_per_lb": 299,
                "effective_from": "2026-04-01",
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_WINDOW_IN_PAST, expected_status=422)

    def test_policy_adjacent_window_accepted(self, api):
        """PRD §3.1: "Windows for the same site may not overlap; an overlapping create is rejected with `ERR_POLICY_WINDOW_OVERLAP`, although adjacency — one window's `effective_to` equal to the next window's `effective_from` — is permitted."
        PRD §3.1: "A policy's `is_current` flag is derived: it is true exactly when `effective_from` is on or before the current logical date and either `effective_to` is null or the current date is strictly before `effective_to`."

        Design: Difficulty/resource_temporal_overlap/pricing_policy_half_open_adjacency
        """
        site = create_site(name="Window Site")
        p1 = add_policy(site["id"], effective_to="2026-05-10")  # [2026-05-01, 2026-05-10)
        # Adjacent: effective_from == P1.effective_to
        p2 = add_policy(site["id"], effective_from="2026-05-10", swap_price_cents=2599)
        assert p2["effective_from"] == "2026-05-10"
        # At the startup clock 2026-05-01, P2's window starts in the future.
        assert p2["is_current"] is False
        p1_read = validate_success(api.get_pricing_policy(p1["id"], ADMIN), 200)
        assert p1_read["is_current"] is True

    def test_policy_one_day_early_overlaps(self, api):
        """PRD §3.1: "Windows for the same site may not overlap; an overlapping create is rejected with `ERR_POLICY_WINDOW_OVERLAP`, although adjacency — one window's `effective_to` equal to the next window's `effective_from` — is permitted."

        Design: Difficulty/resource_temporal_overlap/pricing_policy_half_open_adjacency
        """
        site = create_site(name="Overlap Site")
        add_policy(site["id"], effective_to="2026-05-10")  # [2026-05-01, 2026-05-10)
        version = get_site_version(site["id"])
        res = api.create_pricing_policy(
            {
                "site_id": site["id"],
                "expected_site_version": version,
                "swap_price_cents": 2199,
                "core_deposit_cents": 3500,
                "tax_rate_bps": 825,
                "refill_tier1_cents_per_lb": 349,
                "refill_tier1_max_lbs": 15.00,
                "refill_tier2_cents_per_lb": 299,
                "effective_from": "2026-05-09",  # one day into P1's window
            },
            ADMIN,
        )
        validate_error(res, ApiErrorId.ERR_POLICY_WINDOW_OVERLAP, expected_status=409)
