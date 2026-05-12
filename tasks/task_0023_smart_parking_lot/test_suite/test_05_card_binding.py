"""Card binding cardinality and eligibility (PRD §3.3, §2.7)."""
from __future__ import annotations

import pytest

from test_helpers import (
    advance_clock,
    bind_card_payload,
    bind_vehicle_to_card,
    create_card,
    create_vehicle,
    issue_violation,
    setup_lot_zone_spaces,
    unbind_card_payload,
    unique_holder_ref,
    validate_error,
    validate_success,
)


class TestStoredValueBinding:
    def test_storedvalue_max_one_binding(self, api, operator_headers):
        """PRD §3.3: 'a STORED_VALUE card may have at most one bound vehicle
        ... A breach of the per-card cap (a stored-value card already has
        one binding ...) yields ERR_CARD_BINDING_LIMIT.'"""
        card = create_card(card_type="STORED_VALUE")
        v1 = create_vehicle()
        v2 = create_vehicle()
        bind_vehicle_to_card(card["id"], v1["id"])
        res = api.bind_card(
            card["id"], bind_card_payload(vehicle_id=v2["id"]),
            operator_headers,
        )
        validate_error(res, "ERR_CARD_BINDING_LIMIT")

    def test_unbind_then_rebind_storedvalue(self, api, operator_headers):
        """PRD §3.3: 'Unbinding by vehicle_id removes that vehicle from
        bound_vehicle_ids.' (Round-trip: unbind frees the cap.)"""
        card = create_card(card_type="STORED_VALUE")
        v1 = create_vehicle()
        v2 = create_vehicle()
        bind_vehicle_to_card(card["id"], v1["id"])
        api.unbind_card(
            card["id"], unbind_card_payload(vehicle_id=v1["id"]),
            operator_headers,
        )
        res = api.bind_card(
            card["id"], bind_card_payload(vehicle_id=v2["id"]),
            operator_headers,
        )
        data = validate_success(res, expected_status=200)
        assert v2["id"] in data["bound_vehicle_ids"]


class TestMonthlyBinding:
    def test_monthly_max_four_bindings(self, api, operator_headers):
        """PRD §3.3: 'a MONTHLY card may have at most four bound vehicles
        ... A breach of the per-card cap (... a monthly card already has
        four) yields ERR_CARD_BINDING_LIMIT.'"""
        card = create_card(card_type="MONTHLY", monthly_fee_cents=1000)
        for _ in range(4):
            v = create_vehicle()
            bind_vehicle_to_card(card["id"], v["id"])
        v5 = create_vehicle()
        res = api.bind_card(
            card["id"], bind_card_payload(vehicle_id=v5["id"]),
            operator_headers,
        )
        validate_error(res, "ERR_CARD_BINDING_LIMIT")

    def test_monthly_per_vehicle_global_uniqueness(self, api, operator_headers):
        """PRD §3.3: 'any single vehicle may be bound to at most one MONTHLY
        card across the entire system ... A breach of the cross-card monthly
        invariant (the vehicle is already bound to a different MONTHLY card)
        yields ERR_VEHICLE_ALREADY_BOUND.'"""
        v = create_vehicle()
        a = create_card(card_type="MONTHLY", monthly_fee_cents=1000)
        b = create_card(card_type="MONTHLY", monthly_fee_cents=1000)
        bind_vehicle_to_card(a["id"], v["id"])
        res = api.bind_card(
            b["id"], bind_card_payload(vehicle_id=v["id"]),
            operator_headers,
        )
        validate_error(res, "ERR_VEHICLE_ALREADY_BOUND")


class TestUnbindEdgeCase:
    def test_unbind_vehicle_not_bound_rejected(self, api, operator_headers):
        """PRD §3.3: 'an attempt to unbind a vehicle not currently bound to
        the card is rejected with ERR_VEHICLE_NOT_BOUND.'"""
        card = create_card(card_type="STORED_VALUE")
        v = create_vehicle()
        res = api.unbind_card(
            card["id"], unbind_card_payload(vehicle_id=v["id"]),
            operator_headers,
        )
        validate_error(res, "ERR_VEHICLE_NOT_BOUND")


class TestBindingEligibility:
    def test_bind_with_open_violation_rejected(self, api, operator_headers):
        """PRD §3.3: 'Binding a vehicle to a card requires the vehicle's
        binding_eligible to be true (otherwise ERR_VEHICLE_HAS_OPEN_VIOLATIONS).'"""
        # Set up a vehicle with one open BLOCKING violation (PENDING).
        advance_clock("2026-04-01T10:00:00.000Z")
        lot, zone, spaces = setup_lot_zone_spaces(space_count=1)
        vehicle = create_vehicle()
        issue_violation(
            lot_id=lot["id"],
            vehicle_id=vehicle["id"],
            space_id=spaces[0]["id"],
            violation_type="BLOCKING",
            detected_at="2026-04-01T10:00:00.000Z",
            photo_uri="s3://evidence/p1.jpg",
        )
        card = create_card(card_type="STORED_VALUE")
        res = api.bind_card(
            card["id"], bind_card_payload(vehicle_id=vehicle["id"]),
            operator_headers,
        )
        validate_error(res, "ERR_VEHICLE_HAS_OPEN_VIOLATIONS")


class TestRechargeIdempotency:
    def test_duplicate_external_ref_rejected(self, api, operator_headers):
        """PRD §3.3: 'If external_ref is supplied and already present on
        another Payment, the request is rejected with
        ERR_DUPLICATE_EXTERNAL_REF.'"""
        from test_helpers import recharge_card_payload
        card = create_card(card_type="STORED_VALUE")
        ref = "shared-ext-ref-12345"
        first = api.recharge_card(
            card["id"],
            recharge_card_payload(amount_cents=1000, external_ref=ref),
            operator_headers,
        )
        validate_success(first, expected_status=200)
        second = api.recharge_card(
            card["id"],
            recharge_card_payload(amount_cents=1000, external_ref=ref),
            operator_headers,
        )
        validate_error(second, "ERR_DUPLICATE_EXTERNAL_REF")
