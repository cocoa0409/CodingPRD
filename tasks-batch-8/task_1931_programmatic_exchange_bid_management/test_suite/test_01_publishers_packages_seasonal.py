"""Publisher onboarding defaults, package floors, seasonal windows, listing."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_package,
    assert_publisher,
    assert_seasonal_window,
    create_demand_partner_payload,
    create_package_payload,
    create_publisher,
    create_publisher_payload,
    create_seasonal_window_payload,
    create_window,
    get_package,
    is_valid_uuid,
    make_publisher_manager_headers,
    set_clock,
    setup_active_deal,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers import TEST_USERS

ADMIN = TEST_USERS["exchange_admin_headers"]


class TestPublisherDefaults:
    def test_publisher_creation_defaults_and_system_fields(self, api):
        """PRD §3.1: "When omitted, `payment_terms` defaults to
        `SEQUENTIAL_LIABILITY`. A new publisher starts `ACTIVE` with all derived
        balances — `lifetime_net_micros`, `accrued_open_micros`,
        `paid_out_micros`, `written_off_micros` — at zero, and with
        `active_package_count` at zero."
        PRD §2.6: "`id` is a server-minted UUID with no type prefix."

        Design: Corner/entities/publisher_creation_defaults_and_system_fields
        """
        seed = validate_success(
            api.create_publisher(
                create_publisher_payload("Seed Pub", "seed.com", "GUARANTEED"),
                ADMIN),
            201)
        assert seed["payment_terms"] == "GUARANTEED"

        pub = validate_success(
            api.create_publisher(create_publisher_payload("Pub", "p.com"), ADMIN),
            201)
        assert_publisher(pub)
        assert pub["payment_terms"] == "SEQUENTIAL_LIABILITY", (
            "payment_terms defaults to SEQUENTIAL_LIABILITY when omitted")
        assert pub["status"] == "ACTIVE"
        assert pub["lifetime_net_micros"] == 0
        assert pub["accrued_open_micros"] == 0
        assert pub["paid_out_micros"] == 0
        assert pub["written_off_micros"] == 0
        assert pub["active_package_count"] == 0
        assert is_valid_uuid(pub["id"])
        assert isinstance(pub["version"], int)


class TestPackageBasics:
    def test_package_create_missing_required_floor_rejected(self, api):
        """PRD §3.2: "by supplying a `name`, a dominant `ad_format` of `DISPLAY`,
        `VIDEO`, `NATIVE`, or `AUDIO`, a non-empty array of `category_tags` used
        later by brand-safety category rules, and a `base_floor_cpm_micros` above
        zero."
        PRD §2.8: "Body well-formedness: every required field present, JSON types
        correct, ... else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/package_create_missing_required_floor_rejected
        """
        pub = create_publisher()
        payload = create_package_payload()
        del payload["base_floor_cpm_micros"]
        resp = api.create_package(payload, make_publisher_manager_headers(pub["id"]))
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        _items, meta = validate_paginated(api.list_packages(ADMIN))
        assert meta["total_count"] == 0, "Nothing may be persisted by the rejected create"

    def test_package_effective_floor_identity_without_window(self, api):
        """PRD §3.2: "`current_seasonal_multiplier_bps` is the `multiplier_bps`
        of whichever seasonal pricing window covers the logical clock's current
        UTC date, or the neutral 10,000 basis points when no window covers it.
        `effective_floor_cpm_micros` is the package's `base_floor_cpm_micros`
        multiplied by `current_seasonal_multiplier_bps` and divided by 10,000,
        rounded half-up to integer micros."

        Design: Corner/entities/package_effective_floor_identity_without_window
        """
        pub = create_publisher()
        pkg = validate_success(
            api.create_package(
                create_package_payload(base_floor_cpm_micros=2000000),
                make_publisher_manager_headers(pub["id"])),
            201)
        assert_package(pkg)
        assert pkg["current_seasonal_multiplier_bps"] == 10000, (
            "No covering window: neutral 10,000 bps multiplier")
        assert pkg["effective_floor_cpm_micros"] == 2000000, (
            "Effective floor equals the base floor under the neutral multiplier")


class TestSeasonalWindowOverlap:
    def test_seasonal_window_shared_end_date_overlaps(self, api):
        """PRD §3.2: "Two windows on the same package may not overlap as closed
        intervals: a new window is rejected with `ERR_SEASONAL_WINDOW_OVERLAP`
        when its `start_date` falls on or before an existing window's `end_date`
        while that existing window's `start_date` falls on or before the new
        window's `end_date`; strict adjacency, where one window begins the day
        after the other ends, is allowed."

        Design: Difficulty/resource_temporal_overlap/seasonal_window_closed_interval_overlap
        """
        pub = create_publisher()
        mgr = make_publisher_manager_headers(pub["id"])
        pkg = validate_success(
            api.create_package(create_package_payload(base_floor_cpm_micros=2000000),
                               mgr), 201)
        w1 = validate_success(
            api.create_seasonal_window(
                create_seasonal_window_payload(
                    pkg["id"], name="W1", start_date="2026-11-20",
                    end_date="2026-11-30", multiplier_bps=15000),
                mgr), 201)
        assert_seasonal_window(w1)
        set_clock("2026-11-25T00:00:00Z")

        pkg_live = get_package(pkg["id"])
        assert pkg_live["effective_floor_cpm_micros"] == 3000000, (
            "While W1 covers the clock: 2,000,000 x 15000/10000 = 3,000,000")
        assert pkg_live["current_seasonal_multiplier_bps"] == 15000

        resp = api.create_seasonal_window(
            create_seasonal_window_payload(
                pkg["id"], name="W2", start_date="2026-11-30",
                end_date="2026-12-05", multiplier_bps=12000),
            mgr)
        validate_error(resp, ApiErrorId.ERR_SEASONAL_WINDOW_OVERLAP)

    def test_seasonal_window_strict_adjacency_allowed(self, api):
        """PRD §3.2: "strict adjacency, where one window begins the day after
        the other ends, is allowed."

        Design: Difficulty/resource_temporal_overlap/seasonal_window_closed_interval_overlap
        """
        pub = create_publisher()
        mgr = make_publisher_manager_headers(pub["id"])
        pkg = validate_success(
            api.create_package(create_package_payload(base_floor_cpm_micros=2000000),
                               mgr), 201)
        validate_success(
            api.create_seasonal_window(
                create_seasonal_window_payload(
                    pkg["id"], name="W1", start_date="2026-11-20",
                    end_date="2026-11-30", multiplier_bps=15000),
                mgr), 201)
        w3 = validate_success(
            api.create_seasonal_window(
                create_seasonal_window_payload(
                    pkg["id"], name="W3", start_date="2026-12-01",
                    end_date="2026-12-10", multiplier_bps=12000),
                mgr), 201)
        assert_seasonal_window(w3)
        assert w3["start_date"] == "2026-12-01", (
            "2026-12-01 == W1.end + 1 day: adjacency is not overlap")

    def test_seasonal_overlap_checked_per_package_only(self, api):
        """PRD §3.2: "Two windows on the same package may not overlap as closed
        intervals"

        Design: Corner/validations/seasonal_overlap_checked_per_package_only
        """
        pub1 = create_publisher("P1", "p1.com")
        pub2 = create_publisher("P2", "p2.com")
        pkg1 = validate_success(
            api.create_package(create_package_payload(base_floor_cpm_micros=1000000),
                               make_publisher_manager_headers(pub1["id"])), 201)
        pkg2 = validate_success(
            api.create_package(create_package_payload(base_floor_cpm_micros=1000000),
                               make_publisher_manager_headers(pub2["id"])), 201)
        validate_success(
            api.create_seasonal_window(
                create_seasonal_window_payload(pkg1["id"]),
                make_publisher_manager_headers(pub1["id"])), 201)
        w2 = validate_success(
            api.create_seasonal_window(
                create_seasonal_window_payload(pkg2["id"]),
                make_publisher_manager_headers(pub2["id"])), 201)
        assert_seasonal_window(w2)
        assert w2["package_id"] == pkg2["id"], (
            "Identical closed interval on a different package is not an overlap")


class TestSeasonalWindowLifecycle:
    def test_seasonal_window_get_by_id(self, api):
        """PRD §3.2: "Each window exposes `is_currently_applied`, true exactly
        when the logical clock's current UTC date falls within its inclusive
        bounds."
        PRD §2.4: "Before any operator sets it, the logical clock reads exactly
        2026-08-01T00:00:00Z."

        Design: Corner/endpoints/seasonal_window_get_by_id
        """
        pub = create_publisher()
        mgr = make_publisher_manager_headers(pub["id"])
        pkg = validate_success(
            api.create_package(create_package_payload(base_floor_cpm_micros=1000000),
                               mgr), 201)
        window = validate_success(
            api.create_seasonal_window(create_seasonal_window_payload(pkg["id"]),
                                       mgr), 201)
        fetched = validate_success(api.get_seasonal_window(window["id"], ADMIN))
        assert_seasonal_window(fetched)
        assert fetched["multiplier_bps"] == 15000
        assert fetched["start_date"] == "2026-11-20"
        assert fetched["end_date"] == "2026-11-30"
        assert fetched["is_currently_applied"] is False, (
            "Default clock 2026-08-01 is outside [2026-11-20, 2026-11-30]")

    def test_seasonal_window_delete_restores_neutral_floor(self, api):
        """PRD §3.2: "Creating or deleting a window that covers the current date
        immediately recomputes the package's multiplier and effective floor,
        incrementing the package's `version` when the multiplier actually changes"
        PRD §3.2: "or the neutral 10,000 basis points when no window covers it."

        Design: Corner/calculations/seasonal_window_delete_restores_neutral_floor
        """
        pub = create_publisher()
        mgr = make_publisher_manager_headers(pub["id"])
        pkg = validate_success(
            api.create_package(create_package_payload(base_floor_cpm_micros=2000000),
                               mgr), 201)
        window = validate_success(
            api.create_seasonal_window(create_seasonal_window_payload(pkg["id"]),
                                       mgr), 201)
        set_clock("2026-11-25T00:00:00Z")

        pkg_live = get_package(pkg["id"])
        assert pkg_live["effective_floor_cpm_micros"] == 3000000, (
            "While the window covers the clock: 2,000,000 x 15000/10000")
        version_before_delete = pkg_live["version"]

        resp = api.delete_seasonal_window(window["id"], mgr)
        assert resp.status_code == 204, (
            "Deleting a seasonal window returns 204 No Content")

        pkg_after = get_package(pkg["id"])
        assert pkg_after["current_seasonal_multiplier_bps"] == 10000
        assert pkg_after["effective_floor_cpm_micros"] == 2000000, (
            "Deleting the covering window restores the base floor")
        assert pkg_after["version"] == version_before_delete + 1, (
            "The multiplier changed, so the package version increments by one")


class TestDemandPartnerUniqueness:
    def test_duplicate_seat_id_rejected(self, api):
        """PRD §3.1: "Demand partners are registered by an `ExchangeAdmin` with
        a display `name`, a `seat_id` that must be unique across all demand
        partners — a duplicate is rejected with `ERR_DUPLICATE_SEAT`"

        Design: Corner/validations/duplicate_seat_id_rejected
        """
        first = validate_success(
            api.create_demand_partner(
                create_demand_partner_payload("DP1", "seat-dup", 10, 1000000),
                ADMIN), 201)
        assert first["seat_id"] == "seat-dup"
        resp = api.create_demand_partner(
            create_demand_partner_payload("DP2", "seat-dup", 10, 1000000),
            ADMIN)
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_SEAT)


class TestPublisherListing:
    def test_publisher_list_pagination_limit_offset(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of items returned;
        it defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips a number of items from the start of the result set and
        defaults to 0. ... The `meta` object of list responses carries `limit`,
        `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/publisher_list_pagination_limit_offset
        """
        for name in ("P1", "P2", "P3"):
            validate_success(
                api.create_publisher(
                    create_publisher_payload(name, f"{name.lower()}.com",
                                             "GUARANTEED"),
                    ADMIN), 201)

        page1, meta1 = validate_paginated(
            api.list_publishers(ADMIN, params={"limit": 2, "offset": 0}))
        assert len(page1) == 2
        assert meta1["total_count"] == 3
        assert meta1["has_more"] is True

        page2, meta2 = validate_paginated(
            api.list_publishers(ADMIN, params={"limit": 2, "offset": 2}))
        assert len(page2) == 1
        assert meta2["total_count"] == 3
        assert meta2["has_more"] is False
