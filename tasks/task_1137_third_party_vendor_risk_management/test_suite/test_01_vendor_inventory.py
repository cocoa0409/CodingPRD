"""Vendor inventory: creation defaults, ignored input, 404s, listing,
pagination, soft-archive visibility, uniqueness, and the tier-change log."""
from test_helpers import (
    NON_EXISTENT_UUID,
    ApiErrorId,
    assert_risk_tier_change_log,
    assert_vendor,
    create_vendor,
    parse_iso_instant,
    reset_clock,
    setup_active_vendor,
    tier_change_vendor,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.fixtures import VRM, RO


class TestVendorCreation:
    def test_vendor_creation_returns_201_and_persisted_defaults(self, api):
        """PRD §3.1: "The server stamps `onboarded_by_user_id` from `X-User-ID`,
        initializes `status` to `ONBOARDING`, initializes `criticality_tier` to
        `TIER_3_STANDARD`, sets `composite_risk_score` to 0, and sets
        `tier_posture` to `CLEAN`."

        Design: Corner/entities/vendor_creation_success_returns_201_and_persisted_fields
        """
        reset_clock()
        res = api.create_vendor(
            {"legal_name": "NewVendor", "headquarters_region": "APAC", "service_category": "LEGAL"},
            VRM,
        )
        vendor = validate_success(res, 201)
        assert_vendor(vendor)
        assert vendor["status"] == "ONBOARDING"
        assert vendor["criticality_tier"] == "TIER_3_STANDARD"
        assert vendor["tier_posture"] == "CLEAN"
        assert vendor["composite_risk_score"] == 0
        assert vendor["legal_name"] == "NewVendor"
        assert vendor["headquarters_region"] == "APAC"
        assert vendor["service_category"] == "LEGAL"

    def test_vendor_computed_fields_ignore_input(self, api):
        """PRD §3.1: "If the caller supplies values for `composite_risk_score`,
        `tier_posture`, `id`, `version`, `created_at`, or `updated_at` in the
        creation payload, those values are accepted but ignored — the server
        always mints its own."

        Design: Corner/entities/vendor_computed_fields_ignore_input
        """
        reset_clock()
        res = api.create_vendor(
            {
                "legal_name": "CompIgnore",
                "headquarters_region": "NA",
                "service_category": "BPO",
                "composite_risk_score": 99,
                "tier_posture": "BREACH",
            },
            VRM,
        )
        vendor = validate_success(res, 201)
        assert vendor["composite_risk_score"] == 0
        assert vendor["tier_posture"] == "CLEAN"

    def test_vendor_system_fields_ignore_input(self, api):
        """PRD §3.1: "If the caller supplies values for `composite_risk_score`,
        `tier_posture`, `id`, `version`, `created_at`, or `updated_at` in the
        creation payload, those values are accepted but ignored — the server
        always mints its own."

        Design: Corner/entities/vendor_system_fields_ignore_input
        """
        reset_clock()
        res = api.create_vendor(
            {
                "legal_name": "SysIgnore",
                "headquarters_region": "NA",
                "service_category": "BPO",
                "id": "11111111-1111-1111-1111-111111111111",
                "created_at": "1999-01-01T00:00:00Z",
                "version": 99,
            },
            VRM,
        )
        vendor = validate_success(res, 201)
        assert vendor["id"] != "11111111-1111-1111-1111-111111111111"
        assert parse_iso_instant(vendor["created_at"]).year >= 2026

    def test_vendor_missing_legal_name_rejected(self, api):
        """PRD §3.1: "A `VendorRelationshipManager` opens a new vendor
        relationship by creating a `Vendor` record with `legal_name`,
        `headquarters_region`, and `service_category`."
        PRD §3.16: "which run before uniqueness checks (`ERR_DUPLICATE_KEY`),
        which run before generic payload validation (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/vendor_required_field_missing_returns_invalid_request
        """
        reset_clock()
        res = api.create_vendor(
            {"headquarters_region": "NA", "service_category": "BPO"}, VRM
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)

    def test_vendor_invalid_headquarters_region_rejected(self, api):
        """PRD §2.9: "`Vendor.headquarters_region` ∈ {`NA`, `EMEA`, `APAC`,
        `LATAM`}."
        PRD §3.16: "which run before uniqueness checks (`ERR_DUPLICATE_KEY`),
        which run before generic payload validation (`ERR_INVALID_REQUEST`)."

        Design: Corner/entities/vendor_invalid_enum_headquarters_region
        """
        reset_clock()
        res = api.create_vendor(
            {"legal_name": "BadEnum", "headquarters_region": "ANTARCTICA", "service_category": "BPO"},
            VRM,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_REQUEST.value)


class TestVendorReads:
    def test_get_vendor_not_found(self, api):
        """PRD §2.5: "If any segment fails to resolve, the request is rejected
        with `ERR_NOT_FOUND` (HTTP 404) before any later segment is considered."

        Design: Corner/entities/vendor_get_not_found_returns_404
        """
        reset_clock()
        res = api.get_vendor(NON_EXISTENT_UUID, RO)
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_create_engagement_on_missing_vendor_not_found(self, api):
        """PRD §2.5: "Path-templated resource identifiers resolve left-to-right:
        the vendor identifier is resolved first, then the engagement identifier
        scoped to that vendor, then the child identifier scoped to that
        engagement. If any segment fails to resolve, the request is rejected
        with `ERR_NOT_FOUND` (HTTP 404) before any later segment is considered."

        Design: Corner/entities/vendor_engagement_parent_relationship_required
        """
        reset_clock()
        res = api.create_engagement(
            NON_EXISTENT_UUID,
            {
                "engagement_code": "ORPHAN",
                "service_summary": "x",
                "annual_spend_cents": 100,
                "data_sensitivity": "PUBLIC",
            },
            VRM,
        )
        validate_error(res, ApiErrorId.ERR_NOT_FOUND.value)

    def test_vendor_listing_pagination_fields(self, api):
        """PRD §2.3: "The default value of `limit` is 10, with a minimum of 1 and
        a maximum of 100. The default value of `offset` is 0. List responses
        return the pagination fields `limit`, `offset`, `total_count`, and
        `has_more` in `meta`."

        Design: Corner/entities/vendor_listing_pagination_fields_present
        """
        reset_clock()
        for i in range(3):
            create_vendor(name=f"V{i+1}")
        data, meta = validate_paginated(api.list_vendors(RO))
        assert meta["limit"] == 10
        assert meta["offset"] == 0
        assert meta["total_count"] == 3
        assert meta["has_more"] is False
        assert len(data) == 3

    def test_vendor_list_limit_offset_window(self, api):
        """PRD §2.3: "List endpoints accept the optional query parameters
        `limit` and `offset`."
        PRD §4: "List vendors with optional filters."

        Design: Corner/endpoints/list_endpoints_support_filter_and_pagination
        """
        reset_clock()
        for i in range(3):
            create_vendor(name=f"F{i+1}")
        data, meta = validate_paginated(
            api.list_vendors(RO, params={"status": "ONBOARDING", "limit": 2, "offset": 0})
        )
        assert len(data) == 2
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        # All three vendors are ONBOARDING, so the filtered view is the full set.
        data_all, meta_all = validate_paginated(api.list_vendors(RO))
        assert meta_all["total_count"] == 3

    def test_vendor_legal_name_uniqueness(self, api):
        """PRD §3.1: "The server rejects the creation when another non-archived
        vendor already holds the same `legal_name`, returning
        `ERR_DUPLICATE_KEY` (HTTP 409)."

        Design: Corner/validations/vendor_legal_name_uniqueness
        """
        reset_clock()
        create_vendor(name="DupName")
        res = api.create_vendor(
            {"legal_name": "DupName", "headquarters_region": "EMEA", "service_category": "CLOUD_INFRA"},
            VRM,
        )
        validate_error(res, ApiErrorId.ERR_DUPLICATE_KEY.value)


class TestVendorSoftArchive:
    def test_exited_vendor_excluded_from_default_listing(self, api):
        """PRD §2.10: "Once `archived_at` is non-null, the vendor is excluded
        from uniqueness checks on `legal_name`, excluded from concentration
        aggregation, and excluded from board-report vendor counts. List
        endpoints accept an `include_archived` flag to surface archived vendors
        when needed."

        Design: Corner/entities/soft_deleted_vendor_excluded_from_list_by_default
        """
        ctx = setup_active_vendor(vendor_name="A-Exited")
        e_id = ctx["engagement"]["id"]
        v_id = ctx["vendor"]["id"]
        validate_success(api.initiate_exit(e_id, VRM), 200)
        validate_success(api.finalize_exit(e_id, RO), 200)
        exited = validate_success(api.exit_vendor(v_id, RO), 200)
        assert exited["status"] == "EXITED"
        assert exited["archived_at"] is not None

        other = create_vendor(name="B-Active")

        data, _meta = validate_paginated(api.list_vendors(RO))
        listed_ids = {v["id"] for v in data}
        assert other["id"] in listed_ids
        assert v_id not in listed_ids

        data_inc, _meta = validate_paginated(
            api.list_vendors(RO, params={"include_archived": "true"})
        )
        listed_inc = {v["id"] for v in data_inc}
        assert v_id in listed_inc
        assert other["id"] in listed_inc


class TestTierChangeLog:
    def test_tier_change_log_rows_are_append_only(self, api):
        """PRD §2.4: "Three entities are exceptions and carry only `id` and
        `created_at`: `ConcentrationBucket`, `AuditFinding`, and
        `RiskTierChangeLog` — these do not have `updated_at` and do not have
        `version`."
        PRD §3.11: "On success the server updates `criticality_tier`, writes a
        `RiskTierChangeLog` row recording `from_tier`, `to_tier`, `reason`, and
        `changed_by_user_id`, recomputes `composite_risk_score` (the tier
        multiplier changed), recomputes `next_monitoring_due_at` from the new
        cadence anchored to the most recent cycle's `completed_at` (or to
        vendor activation if no cycles have completed), and increments the
        vendor's `version` by 1."

        Design: Corner/entities/risk_tier_change_log_immutable_no_version_field
        """
        reset_clock()
        vendor = create_vendor(name="ImmutV")
        tier_change_vendor(vendor["id"], "TIER_2_HIGH", reason="bump")

        data, _meta = validate_paginated(api.list_tier_change_log(vendor["id"], RO))
        assert len(data) == 1
        row = data[0]
        assert_risk_tier_change_log(row)
        assert row["from_tier"] == "TIER_3_STANDARD"
        assert row["to_tier"] == "TIER_2_HIGH"
        assert row["reason"] == "bump"
