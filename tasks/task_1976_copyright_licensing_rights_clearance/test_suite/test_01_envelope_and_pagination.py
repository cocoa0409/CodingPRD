"""Pagination envelope and list-worklist retrieval tests."""
import pytest

from test_helpers import (
    ApiErrorId,
    assert_asset,
    create_asset_payload,
    create_rights_holder_payload,
    get_success_data,
    is_iso8601_timestamp,
    make_curator_headers,
    make_officer_headers,
    make_payer_headers,
    make_requester_headers,
    setup_license,
    validate_paginated,
    validate_success,
)


class TestPaginationEnvelope:
    def test_list_assets_default_limit_total_count_and_has_more(self, api):
        """PRD §2.3: "The `limit` defaults to 10, must be at least 1, and may not
        exceed 100. The `offset` defaults to 0. Every list response carries
        `limit`, `offset`, `total_count`, and `has_more` in its `meta` object."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        curator = make_curator_headers("cur_pg_1")
        holder = get_success_data(
            api.create_rights_holder(create_rights_holder_payload(), curator)
        )
        for i in range(12):
            resp = api.create_asset(
                create_asset_payload(
                    title=f"P{i+1:02d}",
                    work_kind="STILL_IMAGE",
                    permitted_media=["PRINT"],
                    rights_holder_id=holder["id"],
                ),
                curator,
            )
            assert resp.status_code == 201

        page1, meta1 = validate_paginated(api.list_assets(curator))
        assert meta1["total_count"] == 12
        assert meta1["has_more"] is True
        assert meta1["limit"] == 10
        assert meta1["offset"] == 0
        assert len(page1) == 10
        for row in page1:
            assert_asset(row)

        page2, meta2 = validate_paginated(api.list_assets(curator, params={"offset": 10}))
        assert meta2["total_count"] == 12
        assert meta2["has_more"] is False
        assert meta2["offset"] == 10
        assert len(page2) == 2

    def test_list_response_envelope_carries_meta_request_fields(self, api):
        """PRD §2.2: "The `api_request_id` is a server-generated unique identifier
        for the request that starts with `req_`." and "The `api_request_timestamp`
        is a server-generated ISO 8601 UTC timestamp with three fractional digits."

        Design: Corner/endpoints/list_pagination_defaults_and_envelope
        """
        curator = make_curator_headers("cur_pg_2")
        holder = get_success_data(
            api.create_rights_holder(create_rights_holder_payload(), curator)
        )
        for i in range(3):
            api.create_asset(
                create_asset_payload(
                    title=f"M{i}",
                    work_kind="STILL_IMAGE",
                    permitted_media=["PRINT"],
                    rights_holder_id=holder["id"],
                ),
                curator,
            )
        resp = api.list_assets(curator)
        body = resp.json()
        assert body["response_type"] == "array"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])


class TestLicenseReverseLookup:
    def test_license_list_filter_by_clearance_request_id(self, api):
        """PRD §2.10: "The license list filters by `asset_id`,
        `clearance_request_id`, `renewal_alert_id`, `lifecycle`, and `fee_status`."

        Design: Corner/endpoints/fk_reverse_reachability_filtered_lists
        """
        holder, asset, req, lic, _rid = setup_license(
            fee_cents=200000,
            requested_units=2,
            use_start_at="2026-09-01T00:00:00Z",
            use_end_at="2026-11-01T00:00:00Z",
        )
        payer = make_payer_headers("fin_fk_1")
        resp = api.list_licenses(payer, params={"clearance_request_id": req["id"]})
        rows, meta = validate_paginated(resp)
        assert meta["total_count"] == 1
        assert len(rows) == 1
        assert rows[0]["id"] == lic["id"]
