"""Response envelope, authentication/authorization, and pagination behavior."""
import pytest

from test_helpers import (
    FLEET,
    HT,
    NON_EXISTENT_UUID,
    PLANT,
    PRO,
    SALES,
    YARD,
    ApiErrorId,
    api_client,
    assert_lumber_index,
    create_customer,
    create_sorting_batch_with_cores,
    create_spec,
    create_spec_payload,
    setup_batch_in_audit,
    sort_core,
    validate_error,
    validate_paginated,
    validate_success,
)


class TestAuthentication:

    def test_missing_role_header_rejected(self):
        """PRD §2.1: "A request whose `X-User-Role` header is missing or does
        not name one of the declared roles is rejected with
        `ERR_UNAUTHENTICATED`."

        Design: Corner/validations/auth_missing_role_header
        """
        resp = api_client.list_specs({"X-User-ID": "operator-1"})
        validate_error(resp, ApiErrorId.ERR_UNAUTHENTICATED)
        assert resp.status_code == 401


class TestAuthorization:

    def test_yard_supervisor_cannot_create_spec(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint per the authorization matrix in §4 is rejected with
        `ERR_UNAUTHORIZED`."
        PRD §4: POST `/pallet-ops/specs` is authorized for PlantManager only.

        Design: Corner/roles/yard_supervisor_cannot_create_spec
        """
        resp = api_client.create_spec(
            create_spec_payload(spec_code="RBAC-1"), YARD)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403

    def test_sales_rep_cannot_sort_core(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint per the authorization matrix in §4 is rejected with
        `ERR_UNAUTHORIZED`."
        PRD §4: POST `/pallet-ops/core-units/{id}/sort` is authorized for
        YardSupervisor only.

        Design: Corner/roles/sales_rep_cannot_sort_cores
        """
        batch, cores = create_sorting_batch_with_cores()
        resp = api_client.sort_core(cores[0]["id"], {"grade": "A"}, SALES)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        core = api_client.get_core_unit(cores[0]["id"], YARD)
        data = validate_success(core)
        assert data["grade"] == "UNSORTED", (
            f"unauthorized sort must not mutate the core, got {data['grade']}"
        )

    def test_fleet_planner_cannot_close_batch(self):
        """PRD §2.1: "A request whose role is recognized but not permitted for
        the target endpoint per the authorization matrix in §4 is rejected with
        `ERR_UNAUTHORIZED`."
        PRD §4: POST `/pallet-ops/core-batches/{id}/close` is authorized for
        ProcurementManager only.

        Design: Corner/roles/fleet_planner_cannot_close_batch
        """
        batch, _cores = setup_batch_in_audit(supplier_name="RBACCo2",
                                             agreed_unit_price_cents=100,
                                             manifest_count=1, grades=("A",))
        assert batch["status"] == "AUDIT"
        resp = api_client.close_batch(batch["id"], FLEET)
        validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED)
        assert resp.status_code == 403
        after = validate_success(api_client.get_core_batch(batch["id"], PRO))
        assert after["status"] == "AUDIT"

    def test_any_role_can_list_customers(self):
        """PRD §2.1: "A seventh pseudo-role, `Any`, denotes shared read access:
        every authenticated role may perform list and detail reads on every
        resource."

        Design: Corner/roles/any_role_can_read
        """
        create_customer("ReadAll")
        resp = api_client.list_customers(HT)
        data = validate_success(resp)
        assert len(data) == 1
        assert data[0]["company_name"] == "ReadAll"


class TestExistenceChecks:

    def test_get_spec_not_found(self):
        """PRD §2.8: "Path existence: resource identifiers embedded in the URL
        path exist, validated left to right, else `ERR_NOT_FOUND` for the first
        missing one."

        Design: Corner/entities/entity_not_found_returns_404
        """
        resp = api_client.get_spec(NON_EXISTENT_UUID, PLANT)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND)
        assert resp.status_code == 404

    def test_core_unit_with_unknown_batch_rejected(self):
        """PRD §2.8: "Reference existence: identifiers carried in the request
        body — such as a `spec_id`, `customer_id`, `core_unit_id`, `batch_id`,
        `route_id`, `order_id`, or `route_stop_id` — exist, else
        `ERR_REFERENCED_NOT_FOUND`."

        Design: Corner/entities/referenced_fk_not_found_returns_404
        """
        resp = api_client.create_core_unit(
            {"batch_id": NON_EXISTENT_UUID, "species": "PINE"}, YARD)
        validate_error(resp, ApiErrorId.ERR_REFERENCED_NOT_FOUND)
        assert resp.status_code == 404


class TestRequestShape:

    def test_spec_missing_board_count_rejected(self):
        """PRD §2.8: "Request shape: required fields are present, types are
        valid, and enum values are in range, else `ERR_INVALID_REQUEST`."
        PRD §3.1: "a `board_count` of at least five covering deck and stringer
        boards together".

        Design: Corner/entities/spec_missing_required_field_returns_invalid_request
        """
        resp = api_client.create_spec(
            {
                "spec_code": "NOBC",
                "length_in": 48,
                "width_in": 40,
                "height_in": 6.0,
                "lumber_species": "PINE",
            },
            PLANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400

    def test_spec_invalid_species_rejected(self):
        """PRD §2.8: "Request shape: required fields are present, types are
        valid, and enum values are in range, else `ERR_INVALID_REQUEST`."
        PRD §3.1: "a `lumber_species` of `PINE`, `OAK`, or `MIXED`".

        Design: Corner/entities/invalid_enum_value_rejected
        """
        resp = api_client.create_spec(
            create_spec_payload(spec_code="BADENUM", lumber_species="BIRCH"),
            PLANT,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)
        assert resp.status_code == 400


class TestPagination:

    def test_list_specs_pagination_envelope(self):
        """PRD §2.3: "The `limit` parameter specifies the maximum number of
        items to return. If not provided, it defaults to 10, with a minimum of
        1 and maximum of 100. The `offset` parameter specifies the number of
        items to skip and defaults to 0."
        PRD §2.3: "Paginated and non-paginated list-based responses include the
        following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/entities/list_endpoint_pagination_envelope
        """
        create_spec(spec_code="S-A")
        create_spec(spec_code="S-B", length_in=42, width_in=42, height_in=5.0,
                    board_count=11, lumber_species="OAK")
        create_spec(spec_code="S-C", length_in=36, width_in=36, height_in=5.0,
                    board_count=9, lumber_species="MIXED")
        resp = api_client.list_specs(PLANT, params={"limit": 2, "offset": 0})
        data, meta = validate_paginated(resp)
        assert resp.json()["response_type"] == "array"
        assert isinstance(meta["api_request_id"], str)
        assert meta["api_request_id"].startswith("req_")
        assert isinstance(meta["api_request_timestamp"], str)
        assert len(data) == 2, f"limit=2 must return 2 entries, got {len(data)}"
        assert meta["total_count"] == 3
        assert meta["has_more"] is True
        assert meta["limit"] == 2
        assert meta["offset"] == 0

    def test_filtered_list_paginates_within_filter(self):
        """PRD §2.3: "Paginated and non-paginated list-based responses include
        the following fields in the `meta` object of the response envelope:
        `limit`, `offset`, `total_count`, and `has_more`."
        PRD §3.3: "The core-unit list filters by `batch_id`, `grade`,
        `processing_status`, and `rework_of_id`."

        Design: Corner/cross_cutting_layers/list_filter_and_pagination_interaction
        """
        batch, cores = create_sorting_batch_with_cores(
            supplier_name="PageCo", agreed_unit_price_cents=100,
            manifest_count=3,
            estimated_grade_mix={"A": 0.33, "B": 0.0, "SCRAP": 0.67},
            num_cores=3)
        sort_core(cores[0]["id"], "SCRAP", condition_notes="x")
        sort_core(cores[1]["id"], "SCRAP", condition_notes="x")
        sort_core(cores[2]["id"], "A")

        resp = api_client.list_core_units(
            YARD, params={"grade": "SCRAP", "limit": 1, "offset": 0})
        data, meta = validate_paginated(resp)
        assert meta["total_count"] == 2, (
            f"total_count must reflect the grade filter, got {meta['total_count']}"
        )
        assert len(data) == 1
        assert meta["has_more"] is True
        assert all(c["grade"] == "SCRAP" for c in data)

        resp2 = api_client.list_core_units(
            YARD, params={"grade": "SCRAP", "limit": 1, "offset": 1})
        data2, meta2 = validate_paginated(resp2)
        assert len(data2) == 1
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert data2[0]["id"] != data[0]["id"]


class TestImmutableMarketData:

    def test_lumber_index_row_carries_no_version(self):
        """PRD §2.4: "A `LumberPriceIndex` row and a `SeasonalPriceIndex` band
        are immutable once published: they carry only `id` and `created_at`,
        and both `updated_at` and `version` are absent from them."

        Design: Corner/entities/lumber_index_immutable_no_version_field
        """
        resp = api_client.create_lumber_index(
            {
                "species": "PINE",
                "price_per_mbf_cents": 400000,
                "effective_from": "2026-07-01T00:00:00Z",
                "effective_to": "2026-09-01T00:00:00Z",
            },
            PRO,
        )
        created = validate_success(resp, expected_status=201)
        assert_lumber_index(created)

        list_resp = api_client.list_lumber_index(PRO, params={"species": "PINE"})
        rows, meta = validate_paginated(list_resp)
        assert meta["total_count"] == 1
        assert_lumber_index(rows[0])
        assert rows[0]["id"] == created["id"]
