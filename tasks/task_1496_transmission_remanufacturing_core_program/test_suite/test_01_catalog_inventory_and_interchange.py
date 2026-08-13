"""Catalog foundations: model creation, hard parts, interchange, stock
adjustments, and the promotion scan fired by a positive adjustment."""
import pytest

from test_helpers import (
    ADMIN,
    ANY_H,
    INV_PLANNER,
    ApiErrorId,
    assert_deposit_invariant,  # noqa: F401  (re-exported convenience)
    assert_hard_part,
    assert_hard_part_availability,
    assert_interchange_mapping,
    assert_reman_order,
    assert_transmission_model,
    create_full_pump_model,
    create_hard_part_payload,
    create_hard_part_record,
    create_interchange_mapping_payload,
    create_mapping,
    create_min_model,
    create_order,
    create_stock_adjustment_payload,
    create_transmission_model_payload,
    get_invoice_for_order,  # noqa: F401
    get_part,
    kit_reserve,
    setup_single_part_hold_order,
    api_client,
    validate_error,
    validate_success,
)


class TestModelCreation:

    def test_model_create_missing_model_code_rejected(self):
        """PRD §3.1: "Creating a model requires a `model_code` unique across all models".
        PRD §2.8: "required fields present, enum values valid, types correct, every window's end strictly after its start, `year_end` at least `year_start`, and quantities, rates, and deposits positive, else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/model_create_missing_required_model_code_rejected
        """
        payload = create_transmission_model_payload()
        payload.pop("model_code")
        resp = api_client.create_transmission_model(payload, ADMIN)
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_model_create_applies_defaults(self):
        """PRD §3.1: "An optional `warranty_days` sets the coverage window in days from shipment and defaults to 365 when omitted."
        PRD §2.10: "A model's `spec_version` starts at 1 on creation and increments by exactly 1 on every update".

        Design: Corner/entities/model_create_applies_defaults
        """
        resp = api_client.create_transmission_model(
            create_transmission_model_payload(), ADMIN)
        data = validate_success(resp, expected_status=201)
        assert_transmission_model(data)
        assert data["warranty_days"] == 365, \
            f"omitted warranty_days must default to 365, got {data['warranty_days']}"
        assert data["spec_version"] == 1, \
            f"spec_version must start at 1, got {data['spec_version']}"


class TestInterchangeCatalog:

    def test_interchange_invalid_tier_rejected(self):
        """PRD §3.1: "Creating a mapping names a `hard_part_id`, a `transmission_model_id`, and a `tier` of `DIRECT` or `ADAPTED`".
        PRD §2.8: "required fields present, enum values valid, types correct, ... else `ERR_INVALID_REQUEST`."

        Design: Corner/entities/interchange_invalid_tier_enum_rejected
        """
        model = create_min_model()
        part = create_hard_part_record()
        resp = api_client.create_interchange_mapping(
            create_interchange_mapping_payload(part["id"], model["id"],
                                               tier="SIDEWAYS"),
            INV_PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_INVALID_REQUEST)

    def test_interchange_duplicate_pair_rejected(self):
        """PRD §3.1: "the pair of part and model must be unique, and a duplicate is rejected with `ERR_DUPLICATE_INTERCHANGE`."

        Design: Corner/entities/interchange_duplicate_pair_rejected
        """
        model = create_min_model()
        part = create_hard_part_record()
        first = api_client.create_interchange_mapping(
            create_interchange_mapping_payload(part["id"], model["id"], "DIRECT"),
            INV_PLANNER,
        )
        mapping = validate_success(first, expected_status=201)
        assert_interchange_mapping(mapping)
        resp = api_client.create_interchange_mapping(
            create_interchange_mapping_payload(part["id"], model["id"], "ADAPTED"),
            INV_PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_DUPLICATE_INTERCHANGE)


class TestAvailabilityAndStockAdjustments:

    def test_availability_reflects_reservations(self):
        """PRD §2.9: "A hard part's `availability` — the read-only difference between `qty_on_hand` and `qty_reserved` — is the only measure the kit allocator consults".
        PRD §3.1: "The system-managed `qty_reserved` starts at 0, and the read-only `availability` always reflects the on-hand quantity minus the reserved quantity."

        Design: Corner/entities/computed_availability_reflects_reservations
        """
        model = create_full_pump_model(required_qty=2)
        part = create_hard_part_record(qty_on_hand=5)
        create_mapping(part["id"], model["id"], "DIRECT")
        order = create_order(model["id"], "BUYER-1")
        kit_reserve(order["id"])

        data = validate_success(api_client.get_hard_part(part["id"], ANY_H))
        assert_hard_part(data)
        assert data["qty_on_hand"] == 5
        assert data["qty_reserved"] == 2, \
            f"kit of 2x PUMP must reserve 2, got {data['qty_reserved']}"
        assert data["availability"] == 3, \
            f"availability must be 5 - 2 = 3, got {data['availability']}"
        assert_hard_part_availability(data)

    def test_negative_stock_adjustment_rejected(self):
        """PRD §3.1: "Any adjustment that would push `qty_on_hand` below zero is rejected with `ERR_NEGATIVE_STOCK`."

        Design: Corner/errors/negative_stock_adjustment_rejected
        """
        part = create_hard_part_record(qty_on_hand=5)
        created_version = part["version"]
        resp = api_client.create_stock_adjustment(
            part["id"],
            create_stock_adjustment_payload(-10, created_version),
            INV_PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_NEGATIVE_STOCK)
        after = get_part(part["id"])
        assert after["qty_on_hand"] == 5, "rejected adjustment must not mutate stock"
        assert after["version"] == created_version, \
            "rejected adjustment must not advance the part version"

    def test_stock_adjustment_promotes_part_hold_order(self):
        """PRD §3.1: "A successful adjustment increments the part's `version` by 1, and a positive delta fires the `PART_HOLD` promotion scan of §2.9."
        PRD §2.9: "the promotion scan walks all `PART_HOLD` orders in `created_at` ascending order, re-runs the full allocation for each, and promotes every order that now fully resolves from `PART_HOLD` to `ASSEMBLY` with fresh reservations."

        Design: Corner/complexity_layers/stock_adjustment_restock_promotes_waiting_order
        """
        model, part, order = setup_single_part_hold_order(p1_qty=1,
                                                          required_qty=2)
        assert order["shortage_parts"] == ["PUMP"]

        resp = api_client.create_stock_adjustment(
            part["id"],
            create_stock_adjustment_payload(2, part["version"]),
            INV_PLANNER,
        )
        updated = validate_success(resp)
        assert updated["qty_on_hand"] == 3
        assert updated["qty_reserved"] == 2, \
            "the promoted order must reserve 2 units from the restock"

        order_after = validate_success(
            api_client.get_reman_order(order["id"], ANY_H))
        assert order_after["status"] == "ASSEMBLY", \
            f"waiting order must auto-promote to ASSEMBLY, got {order_after['status']}"
        assert order_after["shortage_parts"] == []
        assert len(order_after["reserved_parts"]) == 1
        line = order_after["reserved_parts"][0]
        assert line["hard_part_id"] == part["id"]
        assert line["qty"] == 2
        assert line["tier"] == "DIRECT"


class TestOccVersusFiscalFloor:
    """Priority pair on stock adjustments: a stale expected version answers
    ERR_STALE_VERSION even when the delta would also breach the floor."""

    def test_stale_version_beats_negative_stock(self):
        """PRD §2.8: "On a stock adjustment, a stale `expected_hard_part_version` answers `ERR_STALE_VERSION` even when the requested delta would also breach the negative-stock floor."
        PRD §2.7: "the request is rejected with `ERR_STALE_VERSION` (HTTP 412)."

        Design: Difficulty/priority_pair_validation_conflict/stock_adjust_occ_beats_negative_stock
        """
        part = create_hard_part_record(qty_on_hand=5)
        stale_version = part["version"] - 1
        resp = api_client.create_stock_adjustment(
            part["id"],
            create_stock_adjustment_payload(-999, stale_version),
            INV_PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_STALE_VERSION)
        after = get_part(part["id"])
        assert after["qty_on_hand"] == 5, "OCC-rejected adjustment must not mutate stock"

    def test_negative_stock_fires_when_version_current(self):
        """PRD §3.1: "Any adjustment that would push `qty_on_hand` below zero is rejected with `ERR_NEGATIVE_STOCK`."
        PRD §2.7: "applying a stock adjustment to a hard part requires `expected_hard_part_version` matching the part's current `version`."

        Design: Difficulty/priority_pair_validation_conflict/stock_adjust_occ_beats_negative_stock
        """
        part = create_hard_part_record(qty_on_hand=5)
        resp = api_client.create_stock_adjustment(
            part["id"],
            create_stock_adjustment_payload(-999, part["version"]),
            INV_PLANNER,
        )
        validate_error(resp, ApiErrorId.ERR_NEGATIVE_STOCK)
        after = get_part(part["id"])
        assert after["qty_on_hand"] == 5
        assert after["version"] == part["version"]
