"""Correcting a property's baselines, and a denial that hands the item back unchanged."""

from __future__ import annotations

from decimal import Decimal

import pytest

from test_helpers import (
    acknowledged_plan,
    assert_field_equals,
    assert_item_state,
    current_property_version,
    decide_extension,
    list_rows,
    property_patch_payload,
    read_extension,
    read_item,
    read_property,
    request_extension,
    schedule_phase,
    validate_success,
)


@pytest.fixture
def property_awaiting_a_baseline_correction(api):
    """An acknowledged plan over a 200-key house whose commercial baselines are about to move."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "public_areas",
                "category": "GUEST_FACING",
                "standards_reference": "GF-24.1.1",
                "brand_estimated_cost_cents": 700000,
            }
        ],
        legal_name="Ashcombe Hotels LLC",
        contact_email="ops@ashcombeh.example",
        property_overrides={"name": "Ashcombe Kings Wharf"},
    )
    return scenario, current_property_version(api, scenario.property_id)


class TestPropertyCorrectionRewritesBaselines:
    def test_the_supplied_baselines_are_written_and_the_version_moves(
        self, api, brand_manager, property_awaiting_a_baseline_correction
    ):
        """"The brand may correct a property's commercial baselines and retention floor, supplying any
        of `adr_baseline_cents`, `occupancy_baseline_pct`, `minimum_retention_cents` or `room_count`;
        the correction increments the property's `version`".

        Design: Corner/endpoints/property_patch_rewrites_baselines_and_bumps_version
        """
        scenario, version = property_awaiting_a_baseline_correction

        corrected = validate_success(
            api.patch_property(
                scenario.property_id,
                property_patch_payload(
                    adr_baseline_cents=20000,
                    occupancy_baseline_pct=0.80,
                    room_count=250,
                ),
                brand_manager,
            )
        )

        assert_field_equals(corrected, "adr_baseline_cents", 20000, "property")
        assert_field_equals(corrected, "room_count", 250, "property")
        assert_field_equals(corrected, "version", version + 1, "property")
        assert Decimal(str(corrected["occupancy_baseline_pct"])) == Decimal("0.80"), (
            f"the corrected occupancy baseline is 0.80, got {corrected!r}"
        )

    def test_the_fields_the_body_omits_are_left_alone(
        self, api, brand_manager, property_awaiting_a_baseline_correction
    ):
        """"`initial_reserve_balance_cents` is set to the supplied `reserve_balance_cents` and becomes
        the immutable anchor of the reserve-corpus invariant". "The corpus paid in is the property's
        `initial_reserve_balance_cents` — the reserve balance exactly as supplied at property creation,
        pinned once and never changed again — plus `reserve_contributed_total_cents`".

        Design: Corner/endpoints/property_patch_rewrites_baselines_and_bumps_version
        """
        scenario, _version = property_awaiting_a_baseline_correction
        validate_success(
            api.patch_property(
                scenario.property_id,
                property_patch_payload(
                    adr_baseline_cents=20000,
                    occupancy_baseline_pct=0.80,
                    room_count=250,
                ),
                brand_manager,
            )
        )

        prop = read_property(api, scenario.property_id)

        assert_field_equals(prop, "minimum_retention_cents", 5000000, "property")
        assert_field_equals(prop, "reserve_balance_cents", 50000000, "property")
        assert_field_equals(prop, "initial_reserve_balance_cents", 50000000, "property")
        assert_field_equals(prop, "adr_baseline_cents", 20000, "property")
        assert_field_equals(prop, "room_count", 250, "property")

    def test_a_phase_created_afterwards_projects_against_the_new_baselines(
        self, api, brand_manager, property_awaiting_a_baseline_correction
    ):
        """"phases activated afterwards read the new baselines and therefore produce a different figure
        than their create-time projection." "Every phase carries a projection of the revenue its
        closure displaces, computed at creation against the property's baselines as they then stand".

        Design: Corner/endpoints/property_patch_rewrites_baselines_and_bumps_version
        """
        scenario, _version = property_awaiting_a_baseline_correction
        validate_success(
            api.patch_property(
                scenario.property_id,
                property_patch_payload(
                    adr_baseline_cents=20000,
                    occupancy_baseline_pct=0.80,
                    room_count=250,
                ),
                brand_manager,
            )
        )

        phase = schedule_phase(
            api,
            scenario,
            phase_number=1,
            start_date="2026-09-01",
            end_date="2026-09-10",
            rooms_out_of_service=10,
        )

        assert_field_equals(phase, "displacement_revenue_impact_cents", 1120000, "phase")
        assert_field_equals(phase, "status", "PLANNED", "phase")


@pytest.fixture
def item_deferred_behind_a_pending_extension(api):
    """A guest-facing item whose owner has asked for 45 more days, decision still open."""
    scenario = acknowledged_plan(
        api,
        [
            {
                "key": "vanities",
                "category": "GUEST_FACING",
                "standards_reference": "GF-25.1.1",
                "brand_estimated_cost_cents": 1000000,
            }
        ],
        legal_name="Bellhaven Hotels LLC",
        contact_email="ops@bellhavenh.example",
    )
    request = request_extension(
        api,
        scenario,
        scenario.item_id("vanities"),
        45,
        business_justification=(
            "The specified vanity stone is quarried seasonally and the fabricator cannot slab "
            "before November."
        ),
    )
    return scenario, request


class TestExtensionDenialReturnsTheItemToScoped:
    def test_the_pending_request_defers_the_item_without_moving_its_deadline(
        self, api, item_deferred_behind_a_pending_extension
    ):
        """"A new request is created in `SUBMITTED` with `round_number` 1, `granted_days` 0,
        `pressure_ratio_at_decision` null, `decided_by_user_id` null and `decision_note` null. Creating
        it also moves the charged item `SCOPED → DEFERRED_PENDING_EXTENSION` and increments the item's
        `version`; crucially, the item's `deadline_date` does **not** change while the request is
        pending."

        Design: Corner/endpoints/extension_denial_returns_the_item_to_scoped
        """
        scenario, request = item_deferred_behind_a_pending_extension

        assert_field_equals(request, "status", "SUBMITTED", "extension request")
        assert_field_equals(request, "granted_days", 0, "extension request")
        assert request["decided_by_user_id"] is None, (
            f"no decision has been recorded yet, got {request!r}"
        )
        assert_item_state(
            read_item(api, scenario.item_id("vanities")),
            status="DEFERRED_PENDING_EXTENSION",
            deadline_date="2027-04-28",
        )

    def test_the_denial_closes_the_request_at_zero_granted_days(
        self, api, item_deferred_behind_a_pending_extension
    ):
        """"A `DENY` moves the request `SUBMITTED → DENIED`, sets `granted_days` to 0, stores
        `pressure_ratio_at_decision`, `decided_by_user_id` and `decision_note`". "`APPROVED`,
        `APPROVED_PARTIAL` and `DENIED` are the terminal request states".

        Design: Corner/endpoints/extension_denial_returns_the_item_to_scoped
        """
        scenario, request = item_deferred_behind_a_pending_extension

        decided = decide_extension(
            api,
            request["id"],
            "DENY",
            decision_note=(
                "The brand does not accept seasonal quarrying as a schedule excuse for "
                "soft-goods-adjacent scope."
            ),
        )

        assert_field_equals(decided, "status", "DENIED", "extension request")
        assert_field_equals(decided, "granted_days", 0, "extension request")
        assert_field_equals(decided, "decided_by_user_id", "bm-001", "extension request")
        stored = read_extension(api, request["id"])
        assert_field_equals(stored, "item_id", scenario.item_id("vanities"), "extension request")
        assert Decimal(str(stored["pressure_ratio_at_decision"])) == Decimal("0.0000"), (
            "no item of the plan falls due inside the 60-day window, so the measured pressure is "
            f"0.0000, got {stored!r}"
        )

    def test_the_denied_item_comes_back_scoped_with_nothing_granted(
        self, api, item_deferred_behind_a_pending_extension
    ):
        """"and returns the item `DEFERRED_PENDING_EXTENSION → SCOPED` with `extension_days_granted`
        and `deadline_date` unchanged." "each appends a ledger entry of type `EXTENSION_GRANTED`
        carrying the item's id and a `delta_cents` of 0" — which a denial, not being an approval, does
        not do.

        Design: Corner/endpoints/extension_denial_returns_the_item_to_scoped
        """
        scenario, request = item_deferred_behind_a_pending_extension
        decide_extension(
            api,
            request["id"],
            "DENY",
            decision_note=(
                "The brand does not accept seasonal quarrying as a schedule excuse for "
                "soft-goods-adjacent scope."
            ),
        )

        item = read_item(api, scenario.item_id("vanities"))

        assert_item_state(
            item, status="SCOPED", deadline_date="2027-04-28", is_overdue=False
        )
        assert_field_equals(item, "extension_days_granted", 0, "item")
        _rows, meta = list_rows(
            api,
            "list_compliance_ledger_entries",
            plan_id=scenario.plan_id,
            entry_type="EXTENSION_GRANTED",
        )
        assert meta["total_count"] == 0, (
            f"a refused request grants no days and writes no grant row, got {meta}"
        )
