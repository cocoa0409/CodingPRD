"""Corner — cross_cutting_complexity_layers and consistency_model sections.

Optimistic concurrency happy-path, pagination filtering, and immediate
consistency on GET-after-POST.
"""
from test_helpers import (
    validate_success,
    validate_paginated,
    create_marina,
    create_slip,
    create_tenant,
    create_vessel,
    create_lease_payload,
    TEST_USERS,
    make_tenant_headers,
)


class TestOccCorrectVersionSucceeds:

    def test_lease_create_with_matching_slip_version_bumps_version_to_2(self, api):
        """PRD §2.6: "A request that creates a lease must carry `expected_slip_version`, an integer field whose value is the `version` of the target `Slip` as the client last observed it."
        PRD §3.4: "A successful create produces a lease in `RESERVED` state with `nightly_rate_cents` and `total_cost_cents` both defaulting to 0 (they are pinned only at check-in), advances the slip from `AVAILABLE` to `RESERVED`, increments the slip's `version` by 1, and refreshes the slip's `updated_at`."

        Design: Corner/cross_cutting_complexity_layers/occ_correct_version_succeeds
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="OK-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        # Slip created with version 1 per PRD §2.4.
        assert slip["version"] == 1
        tenant = create_tenant()
        vessel = create_vessel(tenant["id"], name="VOK", loa_ft=40, beam_ft=12)
        res = api.create_lease(
            create_lease_payload(
                marina_id=marina["id"],
                slip_id=slip["id"],
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                expected_slip_version=slip["version"],
            ),
            make_tenant_headers(tenant["id"]),
        )
        lease_data = validate_success(res, expected_status=201)
        assert lease_data["status"] == "RESERVED"
        # Slip advanced: status RESERVED, version bumped by 1.
        slip_res = api.get_slip(slip["id"], TEST_USERS["harbor_master_headers"])
        slip_after = validate_success(slip_res, expected_status=200)
        assert slip_after["status"] == "RESERVED"
        assert slip_after["version"] == 2


class TestPaginationLimitOffsetHonoredOnMarinas:

    def test_list_marinas_limit_2_returns_two_with_total_count_three(self, api):
        """PRD §2.3: "List endpoints accept two query parameters: `limit` and `offset`. The `limit` parameter defaults to 10, has a minimum of 1, and a maximum of 100; `offset` defaults to 0 with no upper bound beyond what the underlying data supports."
        PRD §2.3: "The `meta` block of every list response carries `limit`, `offset`, `total_count` (the total matching rows across the entire result set), and `has_more` (true when additional pages remain after the current `offset` + `limit` window)."

        Design: Corner/cross_cutting_complexity_layers/pagination_limit_offset_honored_on_marinas
        """
        create_marina(liveaboard_cap=1, name="P1")
        create_marina(liveaboard_cap=1, name="P2")
        create_marina(liveaboard_cap=1, name="P3")
        res = api.list_marinas(
            TEST_USERS["harbor_master_headers"],
            params={"limit": 2, "offset": 0},
        )
        data, meta = validate_paginated(res)
        assert len(data) == 2, f"limit=2 must return exactly 2 items, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True


class TestImmediateConsistencyLeaseAppearsInGetAfterCreate:

    def test_get_lease_immediately_after_create_returns_reserved(self, api):
        """PRD §3.4: "A successful create produces a lease in `RESERVED` state with `nightly_rate_cents` and `total_cost_cents` both defaulting to 0 (they are pinned only at check-in), advances the slip from `AVAILABLE` to `RESERVED`, increments the slip's `version` by 1, and refreshes the slip's `updated_at`."

        Design: Corner/consistency_model/immediate_consistency_lease_appears_in_get_after_create
        """
        marina = create_marina(liveaboard_cap=1)
        slip = create_slip(
            marina["id"], slip_number="IC-1",
            length_ft=50, beam_ft=15, power_amp="A50",
            base_daily_rate_cents=5000,
        )
        tenant = create_tenant()
        vessel = create_vessel(tenant["id"], name="VIC", loa_ft=40, beam_ft=12)
        create_res = api.create_lease(
            create_lease_payload(
                marina_id=marina["id"],
                slip_id=slip["id"],
                tenant_id=tenant["id"],
                vessel_id=vessel["id"],
                start_date="2026-09-01",
                end_date="2026-09-05",
                expected_slip_version=slip["version"],
            ),
            make_tenant_headers(tenant["id"]),
        )
        created = validate_success(create_res, expected_status=201)
        get_res = api.get_lease(created["id"], TEST_USERS["harbor_master_headers"])
        data = validate_success(get_res, expected_status=200)
        assert data["id"] == created["id"]
        assert data["status"] == "RESERVED"
