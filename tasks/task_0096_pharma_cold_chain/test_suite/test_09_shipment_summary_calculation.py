"""Shipment summary cost calculation — PRD §3.6.

The three-component tiered model: base by zone_type + packaging
surcharge + special-handling premium, with per-line round_half_up
before summing.
"""
from __future__ import annotations

import pytest

from test_helpers import (
    BASE_CENTS_BY_ZONE_TYPE,
    DRY_ICE_MIN_CENTS,
    DRY_ICE_PER_UNIT_CENTS,
    PCM_MAX_CENTS,
    PCM_PER_UNIT_CENTS,
    SPECIAL_PREMIUM_CENTS,
    TEST_USERS,
    create_planned_shipment,
    pack_shipment,
    pick_shipment,
    setup_accepted_lot,
    validate_success,
)


# ===========================================================================
# Helper: build a shipment in PACKED with controllable inputs.
# ===========================================================================
def _build_packed_shipment(
    *, required_zone_type: str, packaging_kind: str,
    quantity_units: int, special_storage_tag: str = "NONE",
    pick_temp_c: float = 5.0, vehicle_precondition_temp_c: float = 5.0,
    accepted_quantity_units: int = 100,
):
    ctx = setup_accepted_lot(
        quantity_units=accepted_quantity_units,
        required_zone_type=required_zone_type,
        special_storage_tag=(
            special_storage_tag if special_storage_tag != "NONE" else None
        ),
    )
    # Choose pick/vehicle temps inside the product's required range.
    # Defaults assume REFRIGERATED (2..8); callers override for other
    # zone types.
    s = create_planned_shipment(
        ctx["warehouse"]["id"], ctx["product"]["id"],
        quantity_units=quantity_units,
        packaging_kind=packaging_kind,
        pick_temp_c=pick_temp_c,
        vehicle_precondition_temp_c=vehicle_precondition_temp_c,
    )
    pick_shipment(s["id"])
    packed = pack_shipment(s["id"])
    return ctx, packed


# ===========================================================================
# Difficulty-design coverage: combinatorial three-input formula.
# # difficulty: combinatorial_formula/shipment_outbound_total_nonlinear_three_input
# ===========================================================================
class TestShipmentSummaryCombinatorial:

    def test_frozen_dry_ice_qty10_uses_floor_2000(self, api):
        """PRD §3.6: "When the `packaging_kind` is `INSULATED_DRY_ICE`,
        the surcharge is the greater of 2000 cents and 100 cents
        multiplied by the shipment's `quantity_units` — that is, a
        floor of 2000 cents and a per-unit rate of 100 cents."

        Difficulty-design: combinatorial_formula /
        shipment_outbound_total_nonlinear_three_input (variant a).
        # difficulty: combinatorial_formula/shipment_outbound_total_nonlinear_three_input

        Claim: FROZEN + DRY_ICE + qty=10 + NONE → base=5000 +
        max(2000, 100*10=1000)=2000 + 0 = 7000 cents.
        """
        ctx, packed = _build_packed_shipment(
            required_zone_type="FROZEN",
            packaging_kind="INSULATED_DRY_ICE",
            quantity_units=10,
            pick_temp_c=-20.0,
            vehicle_precondition_temp_c=-20.0,
        )
        res = api.get_shipment_summary(
            packed["id"], TEST_USERS["picker_headers"],
        )
        data = validate_success(res, 200)
        assert data["total_cents"] == 7000, (
            f"FROZEN+DRY_ICE+qty10 should be 5000+2000+0=7000, got "
            f"{data['total_cents']}"
        )

    def test_refrigerated_pcm_qty20_vaccine_uses_per_unit(self, api):
        """PRD §3.6: "When the `packaging_kind` is `INSULATED_PCM`, the
        surcharge is the smaller of 3000 cents and 50 cents multiplied
        by the shipment's `quantity_units`".
        PRD §3.6: "A special-handling premium of 1000 cents is added
        when the product's `special_storage_tag` is any of `NARCOTIC`,
        `PSYCHOTROPIC`, `BIOLOGICAL`, or `VACCINE`".

        Difficulty-design: combinatorial_formula /
        shipment_outbound_total_nonlinear_three_input (variant b).
        # difficulty: combinatorial_formula/shipment_outbound_total_nonlinear_three_input

        Claim: REFRIGERATED + PCM + qty=20 + VACCINE → 3000 +
        min(3000, 50*20=1000)=1000 + 1000 = 5000 cents.
        """
        # VACCINE tag means the assigned bin must also be VACCINE-tagged
        # under PRD §3.4. Build a custom topology that includes a
        # VACCINE bin.
        from test_helpers import (
            accept_receipt,
            create_bin,
            create_inspected_receipt,
            create_warehouse,
            create_zone,
            setup_qualified_supplier_and_product,
        )
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="REFRIGERATED")
        create_bin(
            z["id"], volume_units=200, weight_limit_kg=1000.0,
            special_storage_tag="VACCINE",
        )
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="REFRIGERATED",
            special_storage_tag="VACCINE",
        )
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=100,
        )
        accept_receipt(receipt["id"])
        s = create_planned_shipment(
            wh["id"], product["id"], quantity_units=20,
            packaging_kind="INSULATED_PCM",
            pick_temp_c=5.0, vehicle_precondition_temp_c=5.0,
        )
        pick_shipment(s["id"])
        packed = pack_shipment(s["id"])
        res = api.get_shipment_summary(
            packed["id"], TEST_USERS["picker_headers"],
        )
        data = validate_success(res, 200)
        # base=3000 (REFRIGERATED) + min(3000, 50*20=1000)=1000 +
        # premium=1000 (VACCINE) = 5000.
        assert data["total_cents"] == 5000, (
            f"Expected 5000, got {data['total_cents']}"
        )

    def test_refrigerated_pcm_qty60_pcm_cap_engaged(self, api):
        """PRD §3.6: "the smaller of 3000 cents and 50 cents multiplied
        by the shipment's `quantity_units`" — the cap engages at
        qty=60 (50*60=3000 == cap).

        Claim: REFRIGERATED + PCM + qty=60 + NONE → base=3000 +
        min(3000, 50*60=3000)=3000 + 0 = 6000 cents (cap engaged
        exactly).
        """
        ctx, packed = _build_packed_shipment(
            required_zone_type="REFRIGERATED",
            packaging_kind="INSULATED_PCM",
            quantity_units=60,
            accepted_quantity_units=100,
        )
        res = api.get_shipment_summary(
            packed["id"], TEST_USERS["picker_headers"],
        )
        data = validate_success(res, 200)
        assert data["total_cents"] == 6000, (
            f"Expected 6000, got {data['total_cents']}"
        )


# ===========================================================================
# Difficulty-design coverage: rounding order — per-line then sum.
# # difficulty: combinatorial_formula/shipment_outbound_total_rounding_order_per_line
# ===========================================================================
class TestShipmentSummaryRoundingOrder:

    def test_cool_ambient_biological_total(self, api):
        """PRD §3.6: "Each component is rounded half-up to whole cents
        in isolation, and the three rounded components are then
        summed to produce the final total (per-line rounding, not
        aggregate rounding".

        Difficulty-design: combinatorial_formula /
        shipment_outbound_total_rounding_order_per_line.
        # difficulty: combinatorial_formula/shipment_outbound_total_rounding_order_per_line

        Claim: COOL + AMBIENT + BIOLOGICAL → base=1500 + surcharge=0 +
        premium=1000 = 2500 cents. The summary response carries the
        per-line breakdown values 1500/0/1000.
        """
        # Build a COOL zone + bin with BIOLOGICAL special_storage_tag,
        # then accept a BIOLOGICAL product.
        from test_helpers import (
            accept_receipt,
            create_bin,
            create_inspected_receipt,
            create_warehouse,
            create_zone,
            setup_qualified_supplier_and_product,
        )
        wh = create_warehouse()
        z = create_zone(wh["id"], zone_type="COOL")
        create_bin(
            z["id"], volume_units=200, weight_limit_kg=1000.0,
            special_storage_tag="BIOLOGICAL",
        )
        qz = create_zone(wh["id"], zone_type="QUARANTINE",
                         capacity_units=1000)
        create_bin(qz["id"], volume_units=1000, weight_limit_kg=10000.0)
        supplier, product = setup_qualified_supplier_and_product(
            required_zone_type="COOL",
            special_storage_tag="BIOLOGICAL",
        )
        # Carrier readings must lie inside the COOL target band 8..15
        # so the inspection computes temp_chain_intact=True and
        # nonconformance_reason=NONE — only then is acceptance allowed
        # per PRD §3.2.
        receipt = create_inspected_receipt(
            wh["id"], supplier["id"], product["id"], quantity_units=5,
            carrier_logger_readings=[
                {"minutes": 0, "temp_c": 10.0},
                {"minutes": 1, "temp_c": 10.0},
            ],
        )
        accept_receipt(receipt["id"])
        # COOL band defaults to 8..15; pick temps inside that.
        # PRD §3.5 packaging-match rule pins COOL → INSULATED_PCM
        # (AMBIENT is reserved for ROOM_TEMP), so we use INSULATED_PCM
        # here. The assertion below reflects the per-PRD computation
        # with PCM, not AMBIENT.
        s = create_planned_shipment(
            wh["id"], product["id"], quantity_units=1,
            packaging_kind="INSULATED_PCM",
            pick_temp_c=10.0, vehicle_precondition_temp_c=10.0,
        )
        pick_shipment(s["id"])
        packed = pack_shipment(s["id"])
        res = api.get_shipment_summary(
            packed["id"], TEST_USERS["picker_headers"],
        )
        data = validate_success(res, 200)
        # base=1500 (COOL) + surcharge=min(3000, 50*1=50)=50 + premium=
        # 1000 (BIOLOGICAL). Per-line round_half_up: 1500, 50, 1000.
        # Total = 2550.
        # The difficulty-design recipe assumed AMBIENT (surcharge=0),
        # but PRD §3.5 disallows AMBIENT for COOL — so the correct
        # per-PRD computation is 2550, not 2500.
        assert data["total_cents"] == 2550, (
            f"Expected COOL+PCM+BIOLOGICAL+qty1 to total 2550 "
            f"(1500+50+1000), got {data['total_cents']}"
        )


# ===========================================================================
# Additional combinations
# ===========================================================================
class TestShipmentSummaryCombinations:

    def test_ambient_packaging_for_room_temp_no_surcharge(self, api):
        """PRD §3.6: "When the `packaging_kind` is `AMBIENT`, the
        surcharge is 0."
        PRD §3.6: "The three components are evaluated independently.
        Each component is rounded half-up to whole cents in isolation,
        and the three rounded components are then summed".

        Difficulty-design: combinatorial_formula /
        shipment_outbound_total_rounding_order_per_line (second
        instance — three components summed independently with one
        component being 0).
        # difficulty: combinatorial_formula/shipment_outbound_total_rounding_order_per_line

        Claim: ROOM_TEMP + AMBIENT + qty=10 + NONE →
        500 + 0 + 0 = 500 cents (zero surcharge, zero premium,
        independent per-line evaluation).
        """
        # ROOM_TEMP defaults: target 15..25.
        ctx, packed = _build_packed_shipment(
            required_zone_type="ROOM_TEMP",
            packaging_kind="AMBIENT",
            quantity_units=10,
            pick_temp_c=20.0,
            vehicle_precondition_temp_c=20.0,
            accepted_quantity_units=20,
        )
        res = api.get_shipment_summary(
            packed["id"], TEST_USERS["picker_headers"],
        )
        data = validate_success(res, 200)
        assert data["total_cents"] == 500
