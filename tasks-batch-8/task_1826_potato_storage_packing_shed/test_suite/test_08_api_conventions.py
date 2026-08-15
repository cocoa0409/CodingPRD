"""API conventions: envelope shape, pagination, list filters, not-found ordering,
RBAC denials, optimistic concurrency, and immediate consistency (PRD §2)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    is_valid_uuid, is_iso8601_timestamp,
    setup_grower_shed_bin_lot,
    create_grower, create_shed, create_bin, create_lot, create_binned_lot, bin_lot,
    assess_lot, apply_inhibitor, hold_lot, create_settlement, refresh_grower,
    refresh_lot, hold_and_condemn_lot, make_grower_headers, NON_EXISTENT_UUID,
    TEST_USERS,
)

ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_headers"]
STORAGE = TEST_USERS["storage_headers"]
QA = TEST_USERS["qa_headers"]
SALES = TEST_USERS["sales_headers"]
SUPERVISOR = TEST_USERS["supervisor_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestEnvelopeShape:
    def test_success_and_error_envelopes(self, api):
        """PRD §2.2: "All successful API responses (those with 2xx status codes) follow this standard envelope format in their JSON body" with `meta.api_request_id`, `meta.api_request_timestamp`, `response_type`, and `data`.
        PRD §2.2: "All error API responses (4xx status codes) follow this standard envelope format" carrying `response_type` "error" with `data.error_id` and `data.message`.

        Design: Corner/endpoints/c_envelope_success_and_error_shape
        """
        resp = api.create_grower({"name": "Grower AJ", "grower_code": "G-AJ"}, ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        assert isinstance(body["meta"]["api_request_id"], str)
        assert body["meta"]["api_request_id"].startswith("req_")
        assert is_iso8601_timestamp(body["meta"]["api_request_timestamp"])
        assert is_valid_uuid(body["data"]["id"])

        err_resp = api.get_shed(NON_EXISTENT_UUID, ADMIN)
        err_body = err_resp.json()
        assert err_resp.status_code == 404
        assert err_body["response_type"] == "error"
        assert err_body["data"]["error_id"] == "ERR_SHED_NOT_FOUND"
        assert isinstance(err_body["data"]["message"], str)
        assert len(err_body["data"]["message"].strip()) > 0


class TestPagination:
    def test_limit_offset_interaction(self, api):
        """PRD §2.3: "`limit` controls the maximum number of items returned: it defaults to 10, must be at least 1, and is capped at 100. `offset` controls how many items are skipped from the front of the result and defaults to 0."
        PRD §2.3: "The `meta` object of a list response carries four pagination fields: `limit`, `offset`, `total_count`, and `has_more`."

        Design: Corner/endpoints/c_pagination_limit_offset_interaction
        """
        from test_helpers import set_clock
        grower = create_grower("Grower AK", "G-AK")
        l_first = create_lot(grower["id"], variety="RUSSET_BURBANK",
                             harvest_date="2026-07-20", original_weight_cwt=100.00)
        set_clock("2026-08-02T00:00:00Z")
        l_second = create_lot(grower["id"], variety="YUKON_GOLD",
                              harvest_date="2026-07-21", original_weight_cwt=50.00)

        page1, meta1 = validate_paginated(
            api.list_field_lots(STORAGE, params={"grower_id": grower["id"], "limit": 1})
        )
        assert meta1["total_count"] == 2
        assert meta1["has_more"] is True
        assert page1[0]["id"] == l_first["id"]  # stable created_at order

        page2, meta2 = validate_paginated(
            api.list_field_lots(STORAGE, params={"grower_id": grower["id"], "limit": 1,
                                                 "offset": 1})
        )
        assert meta2["total_count"] == 2
        assert meta2["has_more"] is False
        assert page2[0]["id"] == l_second["id"]


class TestListFilters:
    def test_filter_by_variety_and_bin(self, api):
        """PRD §3.10: "Field lots are listed across the operation with optional filters on `grower_id`, `bin_id`, `variety`, and `storage_status`."

        Design: Corner/endpoints/c_list_filter_by_variety_and_bin
        """
        grower = create_grower("Grower AL", "G-AL")
        shed = create_shed("Shed DU")
        b1 = create_bin(shed["id"], bin_code="B-1")
        b2 = create_bin(shed["id"], bin_code="B-2")
        l1 = create_binned_lot(grower["id"], b1["id"], variety="RUSSET_BURBANK",
                               harvest_date="2026-07-20", original_weight_cwt=100.00)
        create_binned_lot(grower["id"], b2["id"], variety="YUKON_GOLD",
                          harvest_date="2026-07-21", original_weight_cwt=50.00)

        variety_hits, meta_v = validate_paginated(
            api.list_field_lots(STORAGE, params={"variety": "YUKON_GOLD"})
        )
        assert meta_v["total_count"] == 1
        assert variety_hits[0]["variety"] == "YUKON_GOLD"

        bin_hits, meta_b = validate_paginated(
            api.list_field_lots(STORAGE, params={"bin_id": b1["id"]})
        )
        assert meta_b["total_count"] == 1
        assert bin_hits[0]["id"] == l1["id"]


class TestNotFound:
    def test_missing_shed_returns_404(self, api):
        """PRD §2.8: "For example, a wash-water check posted against a non-existent shed returns `ERR_SHED_NOT_FOUND` before any other rule is consulted, and a settlement read against a non-existent settlement identifier returns `ERR_SETTLEMENT_NOT_FOUND`."

        Design: Corner/entities/c_get_missing_shed_returns_404
        """
        resp = api.get_shed(NON_EXISTENT_UUID, ADMIN)
        validate_error(resp, ApiErrorId.ERR_SHED_NOT_FOUND)

    def test_existence_validated_left_to_right(self, api):
        """PRD §2.8: "Requests targeting nested resources are validated left-to-right along the path. Existence of each path identifier is checked in order — grower, then shed, then bin, then lot, then contract, then order, then run, then audit, then settlement — and the request is rejected with the `404` error corresponding to the first missing identifier."

        Design: Corner/entities/c_not_found_left_to_right_ordering
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower G", grower_code="G-G", shed_name="Shed CB",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        # Work with a fresh INTAKE lot so the assignment gate does not mask existence.
        lot = create_lot(ctx["grower"]["id"], harvest_date="2026-07-28",
                         original_weight_cwt=100.00)

        resp1 = api.create_field_lot(
            NON_EXISTENT_UUID,
            {"variety": "RUSSET_BURBANK", "harvest_date": "2026-07-28",
             "original_weight_cwt": 100.00},
            INTAKE,
        )
        validate_error(resp1, ApiErrorId.ERR_GROWER_NOT_FOUND)

        resp2 = api.assign_bin(NON_EXISTENT_UUID, {"bin_id": ctx["bin"]["id"]}, INTAKE)
        validate_error(resp2, ApiErrorId.ERR_FIELD_LOT_NOT_FOUND)

        resp3 = api.assign_bin(lot["id"], {"bin_id": NON_EXISTENT_UUID}, INTAKE)
        validate_error(resp3, ApiErrorId.ERR_BIN_NOT_FOUND)

    def test_single_resource_gets_return_resource_specific_404(self, api):
        """PRD §2.8: "Existence of each path identifier is checked in order — grower, then shed, then bin, then lot, then contract, then order, then run, then audit, then settlement — and the request is rejected with the `404` error corresponding to the first missing identifier."

        Design: Corner/entities/c_single_resource_gets_return_404_per_resource
        """
        resp = api.get_contract(NON_EXISTENT_UUID, SALES)
        validate_error(resp, ApiErrorId.ERR_CONTRACT_NOT_FOUND)

        resp = api.get_pack_order(NON_EXISTENT_UUID, SALES)
        validate_error(resp, ApiErrorId.ERR_PACK_ORDER_NOT_FOUND)

        resp = api.get_pack_run(NON_EXISTENT_UUID, SUPERVISOR)
        validate_error(resp, ApiErrorId.ERR_PACK_RUN_NOT_FOUND)

        resp = api.get_settlement(NON_EXISTENT_UUID, CLERK)
        validate_error(resp, ApiErrorId.ERR_SETTLEMENT_NOT_FOUND)


class TestRbacDenials:
    def test_grower_cannot_create_contract(self, api):
        """PRD §2.1: "Once a well-formed identity is established, the server checks the role's permission to perform the requested operation; a role attempting an operation outside its scope is rejected with `ERR_INSUFFICIENT_PERMISSIONS` (HTTP 403)."
        PRD §4: POST /potato-shed/contracts is authorized for SalesManager only.

        Design: Corner/rbac/c_rbac_grower_cannot_create_contract_returns_403
        """
        grower = create_grower("Grower AO", "G-AO")
        resp = api.create_contract(
            {"buyer_name": "Buyer AB", "variety": "RUSSET_BURBANK",
             "committed_volume_cwt": 10.00, "price_cents_per_cwt": 2000,
             "grade_min_us1_pct": 50.0,
             "delivery_window_start": "2026-08-01T00:00:00Z",
             "delivery_window_end": "2026-12-01T00:00:00Z", "priority_rank": 1},
            make_grower_headers(grower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_supervisor_cannot_record_wash_check(self, api):
        """PRD §3.7: "Food safety is the province of the `QualityAssuranceManager`, who is deliberately segregated from the `PackLineSupervisor` (the same operator may not run the line) and from intake."
        PRD §4: POST /potato-shed/sheds/{id}/wash-water-checks is authorized for QualityAssuranceManager only.

        Design: Corner/rbac/c_rbac_supervisor_cannot_record_wash_check_returns_403
        """
        shed = create_shed("Shed DX")
        resp = api.record_wash_check(
            shed["id"],
            {"measured_at": "2026-08-01T01:00:00Z", "turbidity_ntu": 2.0,
             "chlorine_ppm": 100, "water_temp_f": 50},
            SUPERVISOR,
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)
        checks, _ = validate_paginated(api.list_wash_checks(shed["id"], QA))
        assert checks == []

    def test_intake_clerk_cannot_allocate(self, api):
        """PRD §2.9: authorization (tier 2) is evaluated before existence (tier 3) — "failures surface as `ERR_INSUFFICIENT_PERMISSIONS`" come before the `ERR_*_NOT_FOUND` family.
        PRD §4: POST /potato-shed/pack-orders/{id}/allocate is authorized for SalesManager only.

        Design: Corner/rbac/c_rbac_intake_clerk_cannot_allocate_returns_403
        """
        resp = api.allocate_order(NON_EXISTENT_UUID, INTAKE)
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_authz_fires_before_existence(self, api):
        """PRD §2.9: the fixed priority order evaluates "2. **Authorization and ownership** — role permission for the operation and any ownership rule" before "3. **Existence** — path identifiers and body foreign-key references, validated left-to-right".

        Design: Corner/validations/c_priority_authz_before_existence
        """
        grower = create_grower("Grower U0", "G-U0")
        # Grower role is outside the IntakeClerk scope of this endpoint; the
        # nonexistent grower id in the path is never reached.
        resp = api.create_field_lot(
            NON_EXISTENT_UUID,
            {"variety": "RUSSET_BURBANK", "harvest_date": "2026-07-28",
             "original_weight_cwt": 100.00},
            make_grower_headers(grower["id"]),
        )
        validate_error(resp, ApiErrorId.ERR_INSUFFICIENT_PERMISSIONS)

    def test_missing_auth_headers_return_400(self, api):
        """PRD §2.1: "A request missing either header, or presenting a malformed value, is rejected with `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER` (HTTP 400)."

        Design: Corner/rbac/c_rbac_missing_auth_header_returns_400
        """
        resp = api.get_shed(NON_EXISTENT_UUID, headers={"Content-Type": "application/json"})
        validate_error(resp, ApiErrorId.ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER)


class TestOptimisticConcurrency:
    def test_assessment_stale_lot_version_rejected(self, api):
        """PRD §2.7: "Creating a grade-out assessment against a field lot requires the client to supply `expected_field_lot_version` carrying the lot's current `version` as last observed. If the lot's `version` has advanced since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Corner/cross_cutting_complexity_layers/c_occ_assessment_stale_version_returns_412
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower AS", grower_code="G-AS", shed_name="Shed EB",
            lot_weight_cwt=500.00, harvest_date="2026-07-28",
        )
        l = ctx["lot"]  # version 2 after bin assignment
        assess_lot(l["id"], l["version"], cumulative_shrink_cwt=10.00,
                   assessment_date="2026-08-01")

        # Stale retry with the pre-first-assessment version: rejected 412.
        resp = api.create_assessment(
            l["id"],
            {"assessment_date": "2026-08-05", "us1_pct": 68.0, "us2_pct": 20.0,
             "cull_pct": 12.0, "cumulative_shrink_cwt": 12.00,
             "expected_field_lot_version": l["version"]},
            STORAGE,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        # Re-read and resubmit with the fresh version: succeeds.
        lot = refresh_lot(l["id"])
        ok = validate_success(api.create_assessment(
            l["id"],
            {"assessment_date": "2026-08-05", "us1_pct": 68.0, "us2_pct": 20.0,
             "cull_pct": 12.0, "cumulative_shrink_cwt": 12.00,
             "expected_field_lot_version": lot["version"]},
            STORAGE,
        ), expected_status=201)
        assert is_valid_uuid(ok["id"])
        assessments, _ = validate_paginated(api.list_assessments(l["id"], STORAGE))
        assert len(assessments) == 2

    def test_settlement_stale_grower_version_rejected(self, api):
        """PRD §2.7: "Creating a grower settlement requires the client to supply `expected_grower_version` carrying the grower's current `version` as last observed. If the grower's `version` has advanced since that read, the create is rejected with `ERR_STALE_VERSION` (HTTP 412)."
        PRD §3.9: "When a settlement for the same season does exist in `PROVISIONAL`, creating the new one flips the old one to `SUPERSEDED` and the new settlement starts in `PROVISIONAL`."

        Design: Corner/cross_cutting_complexity_layers/c_occ_settlement_stale_version_returns_412
        """
        grower = create_grower("Grower AT", "G-AT")
        st1 = create_settlement(grower["id"], grower["version"])

        # The create bumped grower.version, so the captured version is now stale.
        resp = api.create_settlement(
            grower["id"],
            {"season_label": "2026-storage", "expected_grower_version": grower["version"]},
            CLERK,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)

        grower = refresh_grower(grower["id"])
        st2 = create_settlement(grower["id"], grower["version"])
        st1_after = get_success_data(api.get_settlement(st1["id"], CLERK))
        assert st1_after["status"] == "SUPERSEDED"
        assert st2["status"] == "PROVISIONAL"


class TestVersionIncrements:
    def test_version_bumps_on_each_mutation(self, api):
        """PRD §2.4: "`version` is an integer that increments by one on every mutation; it is the field against which optimistic concurrency is checked."
        PRD §2.4: "Any rule that says a mutation "recomputes" a derived field on a parent entity counts as a mutation of that parent and therefore refreshes `updated_at` and bumps `version`."

        Design: Corner/cross_cutting_complexity_layers/c_version_increments_on_each_mutation
        """
        grower = create_grower("Grower AU", "G-AU")
        shed = create_shed("Shed EC")
        bin_ = create_bin(shed["id"])
        lot = create_lot(grower["id"], harvest_date="2026-07-28",
                         original_weight_cwt=500.00)
        assert lot["version"] == 1

        lot = bin_lot(lot["id"], bin_["id"])
        assert lot["version"] == 2

        assess_lot(lot["id"], lot["version"], cumulative_shrink_cwt=10.00,
                   assessment_date="2026-08-01")
        lot = refresh_lot(lot["id"])
        assert lot["version"] == 3  # assessment's shrink re-baseline bumps the lot

        lot = apply_inhibitor(lot["id"], "2026-08-01T00:00:00Z")
        assert lot["version"] == 4

        lot = hold_lot(lot["id"])
        assert lot["version"] == 5


class TestImmediateConsistency:
    def test_read_after_write_reflects_all_side_effects(self, api):
        """PRD §2.10: "Mutations on one entity routinely propagate to others... Each cascade mutates every affected resource independently, refreshing its `updated_at` and incrementing its `version` where the entity carries one."
        PRD §3.1: "A successful assignment sets the lot's `bin_id`, stamps `binned_at` with the current logical clock, transitions the lot to `BINNED`, and bumps the lot's `version`. The bin's `variety_lock`, if previously unset, takes on the lot's variety; the bin's `occupied_cwt` is then maintained as the sum of `available_cwt` over all `BINNED` lots in that bin, recomputed whenever the underlying lots change."

        Design: Corner/consistency_model/c_immediate_read_after_write
        """
        grower = create_grower("Grower AX", "G-AX")
        shed = create_shed("Shed EF")
        bin_ = create_bin(shed["id"])
        lot = create_lot(grower["id"], harvest_date="2026-07-28",
                         original_weight_cwt=250.00)

        bin_lot(lot["id"], bin_["id"])

        lot = refresh_lot(lot["id"])
        assert lot["storage_status"] == "BINNED"
        assert lot["bin_id"] == bin_["id"]

        bins, _ = validate_paginated(api.list_bins(shed["id"], STORAGE))
        assert abs(bins[0]["occupied_cwt"] - 250.00) <= 0.005
        assert bins[0]["variety_lock"] == "RUSSET_BURBANK"
