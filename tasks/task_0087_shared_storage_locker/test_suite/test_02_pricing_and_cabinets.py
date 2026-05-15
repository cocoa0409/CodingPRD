"""Pricing profile and Cabinet onboarding tests (PRD §3.1, §3.2)."""
from __future__ import annotations

import pytest

from test_helpers import (
    ApiErrorId,
    assert_cabinet,
    assert_pricing_profile,
    create_cabinet,
    create_cabinet_payload,
    create_compartment,
    create_pricing_profile_payload,
    setup_cabinet_with_compartment,
    validate_error,
    validate_success,
)


# ===========================================================================
# Pricing-profile creation (PRD §3.2)
# ===========================================================================
class TestPricingProfileCreation:

    def test_create_succeeds_with_valid_inputs(self, api, operator_headers):
        """PRD §3.2: "Before any rental can be priced, an Operator must
        create a pricing profile for the (size_class, rental_mode) pair.
        A profile carries unit_price_cents, deposit_cents, grace_minutes,
        overdue_rate_cents_per_hour, and forced_clearance_hours."

        Claim: valid create returns 201 + a profile with all those fields.
        """
        resp = api.create_pricing_profile(
            create_pricing_profile_payload(), operator_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert_pricing_profile(data)

    def test_duplicate_pair_rejected(self, api, operator_headers):
        """PRD §3.2: "A second profile with the same (size_class,
        rental_mode) pair is rejected with ERR_DUPLICATE_PROFILE."

        Claim: a second (SMALL, HOURLY) profile → ERR_DUPLICATE_PROFILE.
        """
        api.create_pricing_profile(
            create_pricing_profile_payload(size_class="SMALL",
                                           rental_mode="HOURLY"),
            operator_headers,
        )
        resp2 = api.create_pricing_profile(
            create_pricing_profile_payload(size_class="SMALL",
                                           rental_mode="HOURLY"),
            operator_headers,
        )
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_PROFILE.value)

    def test_zero_unit_price_rejected(self, api, operator_headers):
        """PRD §3.2: "the unit price must be strictly positive."

        Claim: unit_price_cents=0 → ERR_BAD_REQUEST.
        """
        resp = api.create_pricing_profile(
            create_pricing_profile_payload(unit_price_cents=0),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_negative_deposit_rejected(self, api, operator_headers):
        """PRD §3.2: "the deposit must be non-negative."

        Claim: deposit_cents=-1 → ERR_BAD_REQUEST.
        """
        resp = api.create_pricing_profile(
            create_pricing_profile_payload(deposit_cents=-1),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    def test_forced_clearance_too_small_rejected(self, api, operator_headers):
        """PRD §3.2: "the forced-clearance horizon (in hours) must be
        strictly greater than grace_minutes divided by sixty."

        Claim: grace_minutes=120 (2h) with forced_clearance_hours=2 fails
        (must be > 2.0, not >=).
        """
        # grace_minutes=120 → 120/60 = 2.0, so forced_clearance_hours must be > 2.
        resp = api.create_pricing_profile(
            create_pricing_profile_payload(
                grace_minutes=120, forced_clearance_hours=2,
            ),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)


# ===========================================================================
# Cabinet onboarding (PRD §3.1)
# ===========================================================================
class TestCabinetOnboarding:

    def test_create_succeeds_with_valid_inputs(self, api, operator_headers):
        """PRD §3.1: "On creation the cabinet's online_status is ONLINE,
        its last_heartbeat_at is null, its capacity_alert_level is NONE,
        and every counter (total_compartments, small_capacity_total,
        medium_capacity_total, large_capacity_total, small_occupancy_pct,
        medium_occupancy_pct, large_occupancy_pct) is zero."

        Claim: a freshly created Cabinet has online_status=ONLINE,
        capacity_alert_level=NONE, last_heartbeat_at=null, every counter=0.
        """
        resp = api.create_cabinet(create_cabinet_payload(), operator_headers)
        data = validate_success(resp, expected_status=201)
        assert_cabinet(data)
        assert data["online_status"] == "ONLINE"
        assert data["capacity_alert_level"] == "NONE"
        assert data.get("last_heartbeat_at") in (None,)
        for f in (
            "total_compartments",
            "small_capacity_total",
            "medium_capacity_total",
            "large_capacity_total",
        ):
            assert data[f] == 0, f"Cabinet.{f} must be 0 on creation, got {data[f]}"
        for f in (
            "small_occupancy_pct",
            "medium_occupancy_pct",
            "large_occupancy_pct",
        ):
            assert data[f] == 0, f"Cabinet.{f} must be 0 on creation, got {data[f]}"

    @pytest.mark.parametrize("invalid_pct", [-1, 101])
    def test_partner_share_pct_out_of_range_rejected(self, api,
                                                    operator_headers,
                                                    invalid_pct):
        """PRD §3.1: "partner_share_pct is an integer from 0 to 100
        inclusive; a value outside this range is rejected with
        ERR_BAD_REQUEST."

        Claim: partner_share_pct in {-1, 101} → ERR_BAD_REQUEST.
        """
        resp = api.create_cabinet(
            create_cabinet_payload(partner_share_pct=invalid_pct),
            operator_headers,
        )
        validate_error(resp, ApiErrorId.ERR_BAD_REQUEST.value)

    @pytest.mark.parametrize("boundary_pct", [0, 100])
    def test_partner_share_pct_boundary_accepted(self, api,
                                                 operator_headers,
                                                 boundary_pct):
        """PRD §3.1: "partner_share_pct is an integer from 0 to 100
        inclusive."

        Claim: partner_share_pct in {0, 100} is accepted (boundary inclusive).
        """
        resp = api.create_cabinet(
            create_cabinet_payload(partner_share_pct=boundary_pct),
            operator_headers,
        )
        data = validate_success(resp, expected_status=201)
        assert data["partner_share_pct"] == boundary_pct


# ===========================================================================
# Compartment creation + slot uniqueness (PRD §3.2)
# ===========================================================================
class TestCompartmentOnboarding:

    def test_create_compartment_initializes_ok_and_idle(self, api,
                                                       operator_headers):
        """PRD §3.2: "Each new compartment starts with operational_status
        = OK and occupancy_status = IDLE; fault_category, active_rental_id,
        holding_item_description, and holding_claim_deadline are null."

        Claim: fresh compartment is OK + IDLE with null sub-fields.
        """
        cabinet = create_cabinet()
        comp = create_compartment(cabinet["id"], slot_number=1,
                                  size_class="SMALL")
        assert comp["operational_status"] == "OK"
        assert comp["occupancy_status"] == "IDLE"
        assert comp.get("fault_category") in (None,)
        assert comp.get("active_rental_id") in (None,)
        assert comp.get("holding_item_description") in (None,)
        assert comp.get("holding_claim_deadline") in (None,)

    def test_duplicate_slot_rejected(self, api, operator_headers):
        """PRD §3.2: "slot_number must be unique within the parent cabinet,
        and a duplicate is rejected with ERR_DUPLICATE_SLOT."

        Claim: creating two compartments with slot_number=1 →
        ERR_DUPLICATE_SLOT on the second.
        """
        cabinet = create_cabinet()
        api.create_compartment(cabinet["id"],
                               {"slot_number": 1, "size_class": "SMALL"},
                               operator_headers)
        resp2 = api.create_compartment(cabinet["id"],
                                       {"slot_number": 1, "size_class": "MEDIUM"},
                                       operator_headers)
        validate_error(resp2, ApiErrorId.ERR_DUPLICATE_SLOT.value)

    def test_compartment_creation_updates_cabinet_capacity_total(
        self, api, operator_headers,
    ):
        """PRD §3.2: "Each new compartment starts with operational_status
        = OK and occupancy_status = IDLE ... and the cabinet's capacity
        counters are recomputed in the same request."
        PRD §3.7: "For each size class, the count of compartments in
        that class becomes small_capacity_total, medium_capacity_total,
        or large_capacity_total."

        Claim: adding two SMALL compartments raises
        Cabinet.small_capacity_total to 2.
        """
        cabinet, comps, _ = setup_cabinet_with_compartment(
            size_class="SMALL", slot_count=2, create_pricing=False,
        )
        from test_helpers import api_client
        fresh = validate_success(api_client.get_cabinet(
            cabinet["id"], operator_headers,
        ))
        assert fresh["small_capacity_total"] == 2
        assert fresh["total_compartments"] == 2


# ===========================================================================
# Nested-path validation (PRD §2.7)
# ===========================================================================
class TestNestedPathValidation:

    def test_missing_cabinet_returns_not_found(self, api, operator_headers):
        """PRD §2.7: "Paths that nest resources (for example
        /cabinets/{cabinet_id}/compartments/{compartment_id}/rentals) are
        validated left-to-right. The cabinet must exist before the
        compartment is looked up; the compartment must exist and belong
        to that cabinet before the rental endpoint runs. Each failure
        surfaces as ERR_NOT_FOUND with no leakage of which segment failed."

        Claim: GET on a non-existent cabinet → ERR_NOT_FOUND.
        """
        resp = api.get_cabinet("00000000-0000-0000-0000-000000000000",
                               operator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)

    def test_compartment_in_wrong_cabinet_returns_not_found(self, api,
                                                            operator_headers):
        """PRD §2.7: "the compartment must exist and belong to that
        cabinet before the rental endpoint runs."

        Claim: GET /cabinets/{cabinet_A}/compartments/{compartment_of_B}
        → ERR_NOT_FOUND.
        """
        cabinet_a = create_cabinet(location_code="A")
        cabinet_b = create_cabinet(location_code="B")
        comp_b = create_compartment(cabinet_b["id"], slot_number=1,
                                    size_class="SMALL")
        resp = api.get_compartment(cabinet_a["id"], comp_b["id"],
                                   operator_headers)
        validate_error(resp, ApiErrorId.ERR_NOT_FOUND.value)
