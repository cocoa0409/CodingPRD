"""Bicycle listing/pagination, owner scoping, OCC-guarded updates, and
bicycle-read authorization (PRD §2.1, §2.3, §2.9, §3.2)."""
from test_helpers import (
    validate_success,
    validate_error,
    validate_paginated,
    ApiErrorId,
    TEST_USERS,
    register_owner,
    register_bicycle,
    owner_headers,
    create_active_partner_org,
    partner_headers,
    file_theft_report,
    flag_report,
)

REGISTRAR = TEST_USERS["registrar_headers"]


class TestBicycleListing:
    def test_bicycle_list_pagination_defaults(self, api):
        """PRD §2.3: "The `limit` parameter caps the number of returned items; it
        defaults to 10, with a minimum of 1 and a maximum of 100. The `offset`
        parameter skips that many items from the front of the result set and
        defaults to 0."
        PRD §2.3: "Paginated list responses carry `limit`, `offset`, `total_count`,
        and `has_more` in the `meta` object of the envelope."

        Design: Corner/entities/bicycle_list_pagination_defaults
        """
        owner = register_owner("o1@x.com", "O One")
        for n in range(1, 13):
            register_bicycle(
                owner,
                serial_number=f"PG{n:04d}",
                photo_url=f"https://x/{n}.jpg",
                declared_value_cents=10000,
            )
        page1, meta1 = validate_paginated(api.list_bicycles(REGISTRAR))
        assert len(page1) == 10, f"default page size must be 10, got {len(page1)}"
        assert meta1["limit"] == 10 and meta1["offset"] == 0
        assert meta1["total_count"] == 12, f"expected total_count 12, got {meta1['total_count']}"
        assert meta1["has_more"] is True, "page 1 of 12 rows at limit 10 must have more"
        page2, meta2 = validate_paginated(api.list_bicycles(REGISTRAR, params={"offset": 10}))
        assert len(page2) == 2, f"offset 10 of 12 rows must return 2, got {len(page2)}"
        assert meta2["has_more"] is False, "final page must not have more"

    def test_list_filter_bicycles_by_owner(self, api):
        """PRD §3.2: "Owners always see only their own bicycles in list views — the
        `current_owner_id` filter is forced to the caller."
        PRD §3.2: "A `Partner` may search across all bicycles as part of
        stolen-registry checks"; registrars and admins see all (§4).

        Design: Corner/endpoints/list_filter_bicycles_by_owner
        """
        owner1 = register_owner("o1@x.com", "O One")
        owner2 = register_owner("o2@x.com", "O Two")
        register_bicycle(owner1, serial_number="FLT001", photo_url="https://x/1.jpg", declared_value_cents=10000)
        register_bicycle(owner1, serial_number="FLT002", photo_url="https://x/2.jpg", declared_value_cents=10000)
        register_bicycle(owner2, serial_number="FLT003", photo_url="https://x/3.jpg", declared_value_cents=10000)

        # Registrar sees every row.
        _all, meta = validate_paginated(api.list_bicycles(REGISTRAR))
        assert meta["total_count"] == 3, (
            f"registrar must see all 3 bicycles, got {meta['total_count']}"
        )
        # The owner-scoped view is forced to the caller's own bicycles.
        own, own_meta = validate_paginated(api.list_bicycles(owner_headers(owner1)))
        assert own_meta["total_count"] == 2, (
            f"owner1 must see exactly 2 own bicycles, got {own_meta['total_count']}"
        )
        assert all(b["current_owner_id"] == owner1["id"] for b in own), (
            "owner list view must contain only rows owned by the caller"
        )
        own2, own2_meta = validate_paginated(api.list_bicycles(owner_headers(owner2)))
        assert own2_meta["total_count"] == 1
        assert own2[0]["current_owner_id"] == owner2["id"]


class TestBicyclePatchOcc:
    def test_bicycle_patch_stale_version_rejected(self, api):
        """PRD §2.9: "An owner's update to a bicycle's descriptive fields must carry
        `expected_bicycle_version`, set to the `version` of the `Bicycle` the client
        last observed. If the bicycle's current `version` has advanced past that
        value — because another write landed in between — the update is rejected
        with `ERR_STALE_VERSION` (HTTP 412), forcing the client to re-read before
        overwriting."
        PRD §3.2: "A successful update increments `version` by 1."

        Design: Corner/cross_cutting_layers/bicycle_patch_stale_version_rejected
        """
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="OCC100")
        observed_version = bicycle["version"]
        first = api.patch_bicycle(
            bicycle["id"],
            {"expected_bicycle_version": observed_version, "primary_color": "Blue"},
            owner_headers(owner),
        )
        patched = validate_success(first)
        assert patched["version"] == observed_version + 1, (
            f"successful patch must bump version to {observed_version + 1}, "
            f"got {patched['version']}"
        )
        stale = api.patch_bicycle(
            bicycle["id"],
            {"expected_bicycle_version": observed_version, "primary_color": "Green"},
            owner_headers(owner),
        )
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION, expected_status=412)

    def test_cross_owner_bicycle_patch_forbidden(self, api):
        """PRD §2.1: "ownership checks on any resource that references an owner —
        bicycles, transfers, theft reports, claims, bids, event registrations,
        notifications — compare the resource's owner foreign-key field to
        `X-User-ID`, and a mismatch is rejected with
        `ERR_FORBIDDEN_RESOURCE_ACCESS` (HTTP 403)."

        Design: Corner/rbac/cross_owner_bicycle_patch_forbidden
        """
        owner1 = register_owner("o1@x.com", "O One")
        owner2 = register_owner("o2@x.com", "O Two")
        bicycle = register_bicycle(owner1, serial_number="RBC400")
        resp = api.patch_bicycle(
            bicycle["id"],
            {"expected_bicycle_version": bicycle["version"], "primary_color": "Blue"},
            owner_headers(owner2),
        )
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS, expected_status=403)


class TestPartnerBicycleRead:
    def test_partner_read_non_stolen_bicycle_forbidden(self, api):
        """PRD §3.2: "a partner sees the full record only while the bicycle's
        `registry_status` is `STOLEN`."
        PRD §2.6: "owner-scoped endpoints are restricted to the acting owner's own
        resources, and partner endpoints to the acting partner's own organization,
        as described in §2.1; failures yield `ERR_FORBIDDEN_RESOURCE_ACCESS`."

        Design: Corner/rbac/partner_read_non_stolen_bicycle_forbidden
        """
        org = create_active_partner_org()
        owner = register_owner("o1@x.com", "O One")
        bicycle = register_bicycle(owner, serial_number="RBC500")
        # REGISTERED bicycle: partner read is forbidden.
        resp = api.get_bicycle(bicycle["id"], partner_headers(org))
        validate_error(resp, ApiErrorId.ERR_FORBIDDEN_RESOURCE_ACCESS, expected_status=403)
        # Once the bicycle is STOLEN, the same partner read succeeds.
        report = file_theft_report(owner, bicycle)
        flag_report(report["id"])
        ok = api.get_bicycle(bicycle["id"], partner_headers(org))
        data = validate_success(ok)
        assert data["registry_status"] == "STOLEN"
