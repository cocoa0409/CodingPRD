"""Immutable record shape, grower create round-trip, audit lifecycle, contract
conditional fields, pool-price fallback filtering, and storage-week floor
precision (PRD §2.4, §3.3, §3.7, §3.9)."""
import pytest

from test_helpers import (
    validate_success, validate_error, validate_paginated, get_success_data, ApiErrorId,
    is_valid_uuid, is_iso8601_timestamp,
    setup_grower_shed_bin_lot, setup_grower_with_closed_lot,
    create_grower, create_shed, create_bin, create_lot, create_binned_lot,
    assess_lot, hold_and_condemn_lot, create_contract, create_settlement,
    refresh_grower, refresh_shed, set_clock,
    TEST_USERS, make_grower_headers, make_clerk_headers,
)

ADMIN = TEST_USERS["admin_headers"]
INTAKE = TEST_USERS["intake_headers"]
STORAGE = TEST_USERS["storage_headers"]
QA = TEST_USERS["qa_headers"]
SALES = TEST_USERS["sales_headers"]
CLERK = TEST_USERS["clerk_headers"]


class TestGrowerCreate:
    def test_create_returns_201_with_server_fields(self, api):
        """PRD §2.4: "`id` is a server-minted UUID string with no type prefix. `created_at` is an ISO 8601 UTC timestamp with three fractional digits recording when the resource was created. ... `version` is an integer that increments by one on every mutation".
        PRD §2.5: "On startup, before any operator intervention, the logical clock reads exactly `2026-08-01T00:00:00Z`."

        Design: Corner/entities/c_grower_create_returns_201_with_server_fields
        """
        resp = api.create_grower({"name": "Grower A", "grower_code": "G-A"}, ADMIN)
        body = resp.json()
        assert resp.status_code == 201
        assert body["response_type"] == "object"
        data = body["data"]
        assert is_valid_uuid(data["id"])
        assert data["version"] == 1
        # PRD §2.4 pins only the ISO 8601 three-fractional-digit format for created_at;
        # §2.5's logical-clock stamp list (binned_at, closed_at, completed_at, paid_at,
        # audit closed_at) does not include created_at, so no clock value is asserted.
        assert is_iso8601_timestamp(data["created_at"])

        got = validate_success(api.get_grower(data["id"], CLERK), expected_status=200)
        assert got["name"] == "Grower A"
        assert got["grower_code"] == "G-A"


class TestAssessmentImmutability:
    def test_assessment_response_has_no_version_or_updated_at(self, api):
        """PRD §2.4: "Three subordinate resource types are immutable after creation and therefore omit both `updated_at` and `version`, carrying only `id` and `created_at`: `GradeOutAssessment`, `PackRunLotDraw`, and `WashWaterCheck`."
        PRD §3.2: "The assessment itself derives `packable_fraction` — the sum of `us1_pct` and `us2_pct` divided by 100, carried at four decimal places".

        Design: Corner/entities/c_assessment_append_only_immutability
        """
        ctx = setup_grower_shed_bin_lot(
            grower_name="Grower F", grower_code="G-F", shed_name="Shed CA",
            lot_weight_cwt=100.00, harvest_date="2026-07-28",
        )
        l = ctx["lot"]
        resp = api.create_assessment(
            l["id"],
            {"assessment_date": "2026-08-01", "us1_pct": 70.0, "us2_pct": 20.0,
             "cull_pct": 10.0, "cumulative_shrink_cwt": 5.00,
             "expected_field_lot_version": l["version"]},
            STORAGE,
        )
        data = validate_success(resp, expected_status=201)
        assert is_valid_uuid(data["id"])
        assert is_iso8601_timestamp(data["created_at"])
        assert "version" not in data
        assert "updated_at" not in data
        assert abs(data["packable_fraction"] - 0.9) <= 0.00005  # (70+20)/100, computed

        assessments, _ = validate_paginated(api.list_assessments(l["id"], STORAGE))
        assert len(assessments) == 1
        assert abs(assessments[0]["cumulative_shrink_cwt"] - 5.00) <= 0.005


class TestOrderConditionalFields:
    def test_contract_order_requires_contract_id(self, api):
        """PRD §3.3: "Supplying a `contract_id` on an `OPEN_MARKET` order, or omitting the market price on one, or omitting the contract reference on a `CONTRACT` order, is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/c_order_conditional_fields_return_400
        """
        shed = create_shed("Shed DI")
        resp = api.create_pack_order(
            {"order_type": "CONTRACT", "shed_id": shed["id"], "variety": "RUSSET_BURBANK",
             "pack_unit_weight_lbs": 50, "grade_min_us1_pct": 50.0,
             "requested_packed_cwt": 10.00},
            SALES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_open_market_order_requires_market_price(self, api):
        """PRD §3.3: "Supplying a `contract_id` on an `OPEN_MARKET` order, or omitting the market price on one, or omitting the contract reference on a `CONTRACT` order, is `ERR_INVALID_REQUEST`."

        Design: Corner/validations/c_order_conditional_fields_return_400
        """
        shed = create_shed("Shed DI")
        resp = api.create_pack_order(
            {"order_type": "OPEN_MARKET", "shed_id": shed["id"], "variety": "RUSSET_BURBANK",
             "pack_unit_weight_lbs": 50, "grade_min_us1_pct": 50.0,
             "requested_packed_cwt": 10.00},
            SALES,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)


class TestAuditLifecycle:
    def test_close_twice_returns_audit_invalid_state(self, api):
        """PRD §3.7: "Closing an audit supplies an `outcome`, plus `critical_findings` and `minor_findings` counts; only a `FIELD_WORK` audit can be closed, else `ERR_AUDIT_INVALID_STATE`."

        Design: Corner/state_machines/c_audit_close_twice_returns_audit_invalid_state
        """
        shed = create_shed("Shed CG")
        audit = get_success_data(api.create_audit(shed["id"], {"field_work_date": "2026-08-05"}, QA))
        closed = validate_success(api.close_audit(
            audit["id"], {"outcome": "PASS", "critical_findings": 0, "minor_findings": 1}, QA
        ), expected_status=200)
        assert closed["status"] == "PASSED"

        resp = api.close_audit(
            audit["id"], {"outcome": "FAIL", "critical_findings": 2, "minor_findings": 0}, QA
        )
        validate_error(resp, ApiErrorId.ERR_AUDIT_INVALID_STATE)

        audits, _ = validate_paginated(api.list_audits(shed["id"], QA))
        assert audits[0]["outcome"] == "PASS"
        shed = refresh_shed(shed["id"])
        assert shed["posture"] == "NORMAL"


class TestPoolFallbackFiltering:
    def test_contract_blend_fallback_excludes_settled_contracts(self, api):
        """PRD §3.9: "When no shipped order exists at all, the fallback is the contract blend: the sum over every `ACTIVE` contract of its `committed_volume_cwt` times `price_cents_per_cwt` divided by the total committed volume across those contracts, again rounded half-up to two decimals."
        PRD §3.9: "for a lot not yet closed, the term is its actual `packed_total_cwt` plus the estimated packout of the remainder (the lot's `available_cwt` multiplied by its latest-assessment packout fraction, defaulting to 0.75 when the lot has no assessment)".

        Design: Corner/calculations/c_pool_fallback_contract_blend_filters_settled
        """
        set_clock("2026-08-02T00:00:00Z")
        grower = create_grower("Grower R", "G-R")
        shed = create_shed("Shed DB")
        bin_ = create_bin(shed["id"])
        create_binned_lot(grower["id"], bin_["id"], harvest_date="2026-07-28",
                          original_weight_cwt=100.00)
        create_contract(committed_volume_cwt=100.00, price_cents_per_cwt=2000,
                        buyer_name="Buyer T1", priority_rank=1)
        create_contract(committed_volume_cwt=300.00, price_cents_per_cwt=4000,
                        buyer_name="Buyer T2", priority_rank=2)
        create_contract(committed_volume_cwt=1000.00, price_cents_per_cwt=9999,
                        buyer_name="Buyer T3", priority_rank=3,
                        delivery_window_end="2026-08-10T00:00:00Z")
        # Advance past T3's window end: it auto-settles SHORTFALLED and leaves the pool.
        set_clock("2026-08-11T00:00:00Z")

        grower = refresh_grower(grower["id"])
        st = create_settlement(grower["id"], grower["version"])

        # (100x2000 + 300x4000) / 400 = 3500.00; the SHORTFALLED 9999 contract is excluded.
        assert abs(st["pool_price_cents"] - 3500.00) <= 0.005
        # Unclosed lot: available 100.00 x default fraction 0.75 (no assessment recorded).
        assert abs(st["packed_cwt_basis"] - 75.00) <= 0.005


class TestStorageWeeksFloor:
    def test_thirteen_days_is_one_week_fourteen_is_two(self, api):
        """PRD §3.9: "for the final variant it is the whole weeks between `binned_at` and `closed_at`. Exactly fourteen days in storage counts as exactly two weeks."

        Design: Corner/calculations/c_storage_weeks_floor_boundary
        """
        set_clock("2026-08-02T00:00:00Z")
        ga = create_grower("Grower SA", "G-SA")
        gb = create_grower("Grower SB", "G-SB")
        shed = create_shed("Shed DC")
        bin_ = create_bin(shed["id"])
        la = create_binned_lot(ga["id"], bin_["id"], harvest_date="2026-07-28",
                               original_weight_cwt=200.00)
        lb = create_binned_lot(gb["id"], bin_["id"], harvest_date="2026-07-28",
                               original_weight_cwt=200.00)

        # Lot A condemned at 13 days -> floor(13/7) = 1 completed week.
        set_clock("2026-08-15T00:00:00Z")
        hold_and_condemn_lot(la["id"], "WASTE")
        # Lot B condemned at exactly 14 days -> floor(14/7) = 2 weeks exactly.
        set_clock("2026-08-16T00:00:00Z")
        hold_and_condemn_lot(lb["id"], "WASTE")

        ga = refresh_grower(ga["id"])
        gb = refresh_grower(gb["id"])
        sta = create_settlement(ga["id"], ga["version"])
        stb = create_settlement(gb["id"], gb["version"])

        fin_a = validate_success(
            api.finalize_settlement(sta["id"], make_clerk_headers("clerk_one")),
            expected_status=200,
        )
        fin_b = validate_success(
            api.finalize_settlement(stb["id"], make_clerk_headers("clerk_one")),
            expected_status=200,
        )
        # fee A: 1 week x 12.5 x 200.00 = 2500.00
        assert abs(fin_a["storage_fees_cents"] - 2500.00) <= 0.005
        # fee B: 2 weeks x 12.5 x 200.00 = 5000.00 (14 days is NOT 1 week)
        assert abs(fin_b["storage_fees_cents"] - 5000.00) <= 0.005
