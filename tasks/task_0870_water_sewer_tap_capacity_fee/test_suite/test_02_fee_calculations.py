"""Capacity, tap, and total-fee calculations assessed at approval (PRD §3.4)."""
import pytest
from test_helpers import approved_application


class TestCapacityFeeNewVsRedevelopment:
    """Two applications identical but for assessment_basis diverge: NEW charges full ERU,
    REDEVELOPMENT nets prior_credit_eru — the dual variant on the cost-accounting domain."""

    def test_new_basis_charges_full_eru(self, api):
        """PRD §3.4: "Under the `NEW` basis, the net capacity equals that base factor in full."
        PRD §3.4: "The two components are summed and multiplied by the use multiplier drawn
        from `use_multipliers` for the application's `use_type`. That single product is rounded
        half up to whole cents and stored as `capacity_fee_cents`."

        Design: Difficulty/dual_variant_calc/capacity_fee_new_vs_redevelopment
        """
        app = approved_application(service_type="BOTH", use_type="RESIDENTIAL",
                                   meter_size="ONE", eru_factor=2.5,
                                   assessment_basis="NEW", parcel_id="APN-A")
        assert app["capacity_fee_cents"] == 2250000

    def test_redevelopment_basis_nets_prior_credit(self, api):
        """PRD §3.4: "Under the `REDEVELOPMENT` basis, the net capacity is the base factor
        reduced by the application's `prior_credit_eru`, but never below zero — the credit for
        a prior or abandoned connection cannot produce a negative charge."

        Design: Difficulty/dual_variant_calc/capacity_fee_new_vs_redevelopment
        """
        app = approved_application(service_type="BOTH", use_type="RESIDENTIAL",
                                   meter_size="ONE", eru_factor=2.5,
                                   assessment_basis="REDEVELOPMENT", prior_credit_eru=1.0,
                                   parcel_id="APN-B")
        assert app["capacity_fee_cents"] == 1350000


class TestCapacityFeeCombinatorial:
    """capacity_fee combines eru_factor, a service-type branch, and a use-type multiplier in a
    non-linear interaction, not a linear per-input sum."""

    def test_commercial_multiplier_applied(self, api):
        """PRD §3.4: "The two components are summed and multiplied by the use multiplier drawn
        from `use_multipliers` for the application's `use_type`. That single product is rounded
        half up to whole cents and stored as `capacity_fee_cents`."

        Design: Difficulty/combinatorial_formula/capacity_fee_tiered_multi_input_mode_a
        """
        app = approved_application(service_type="BOTH", use_type="COMMERCIAL",
                                   meter_size="ONE", eru_factor=2.5,
                                   assessment_basis="NEW", parcel_id="APN-C")
        assert app["capacity_fee_cents"] == 2587500

    def test_use_multiplier_is_multiplicative_not_additive(self, api):
        """PRD §3.4: "the `water_capacity_fee_per_eru_cents` is multiplied by the net capacity
        to give the water component, counted only when the `service_type` is `WATER` or `BOTH`
        and otherwise zero; the `sewer_capacity_fee_per_eru_cents` is multiplied by the net
        capacity to give the sewer component, counted only when the `service_type` is `SEWER`
        or `BOTH` and otherwise zero."

        Design: Difficulty/combinatorial_formula/capacity_fee_tiered_multi_input_mode_a
        """
        commercial = approved_application(service_type="BOTH", use_type="COMMERCIAL",
                                          meter_size="ONE", eru_factor=2.5,
                                          assessment_basis="NEW", parcel_id="APN-C2")
        # (400000 + 500000) * 2.5 = 2,250,000 base; COMMERCIAL 1.15 multiplier -> 2,587,500.
        assert commercial["capacity_fee_cents"] == 2587500
        assert commercial["capacity_fee_cents"] != 2250000  # not the un-multiplied base


class TestTotalFeesDueOrderDependent:
    """total_fees_due has a pinned evaluation order: the discount is keyed on gross, which
    depends on admin_fee, which depends on subtotal."""

    def test_total_reflects_admin_cap_then_discount(self, api):
        """PRD §3.4: "The administrative fee is the subtotal multiplied by `admin_fee_pct`,
        rounded half up to whole cents, then capped so it never exceeds `admin_fee_cap_cents`
        — the smaller of the rounded fee and the cap. The gross is the subtotal plus the
        administrative fee. A volume discount applies only when the gross is at least
        `volume_discount_threshold_cents`: in that case the discount is the gross multiplied by
        `volume_discount_pct`, rounded half up to whole cents; otherwise the discount is zero.
        The total is the gross minus the discount, stored as `total_fees_due_cents`."

        Design: Difficulty/combinatorial_formula/total_fees_due_order_dependent_mode_c
        """
        app = approved_application(service_type="BOTH", use_type="RESIDENTIAL",
                                   meter_size="ONE", eru_factor=2.5, tap_install_fee_cents=250000,
                                   assessment_basis="NEW", parcel_id="APN-D")
        assert app["total_fees_due_cents"] == 2422500

    def test_derived_components_feed_subtotal(self, api):
        """PRD §3.4: "The subtotal is `capacity_fee_cents` plus `tap_fee_cents`."

        Design: Difficulty/combinatorial_formula/total_fees_due_order_dependent_mode_c
        """
        app = approved_application(service_type="BOTH", use_type="RESIDENTIAL",
                                   meter_size="ONE", eru_factor=2.5, tap_install_fee_cents=250000,
                                   assessment_basis="NEW", parcel_id="APN-D2")
        assert app["capacity_fee_cents"] == 2250000
        assert app["tap_fee_cents"] == 250000
        assert app["total_fees_due_cents"] == 2422500


def test_tap_fee_with_pavement_cut_surcharge(api):
    """PRD §3.4: "It is the `tap_install_fee_cents` of the meter-size schedule row for the
    application's `meter_size`, plus the rate card's `pavement_cut_surcharge_cents` when
    `requires_pavement_cut` is true, and only the schedule fee otherwise. The result is stored
    as `tap_fee_cents`."

    Design: Corner/calculations/tap_fee_with_pavement_cut_surcharge
    """
    app = approved_application(service_type="WATER", use_type="RESIDENTIAL",
                               meter_size="ONE", eru_factor=2.5, tap_install_fee_cents=250000,
                               requires_pavement_cut=True, parcel_id="APN-PV")
    assert app["tap_fee_cents"] == 330000


def test_capacity_fee_water_only_service_branch(api):
    """PRD §3.4: "the `sewer_capacity_fee_per_eru_cents` is multiplied by the net capacity to
    give the sewer component, counted only when the `service_type` is `SEWER` or `BOTH` and
    otherwise zero."

    Design: Corner/calculations/capacity_fee_water_only_service_branch
    """
    app = approved_application(service_type="WATER", use_type="RESIDENTIAL",
                               meter_size="FIVE_EIGHTH", eru_factor=1.0,
                               tap_install_fee_cents=150000, parcel_id="APN-W")
    assert app["capacity_fee_cents"] == 400000
    assert app["total_fees_due_cents"] == 566500


def test_redevelopment_credit_floors_at_zero(api):
    """PRD §3.4: "Under the `REDEVELOPMENT` basis, the net capacity is the base factor reduced
    by the application's `prior_credit_eru`, but never below zero — the credit for a prior or
    abandoned connection cannot produce a negative charge."

    Design: Corner/calculations/redevelopment_credit_zero_floor
    """
    app = approved_application(service_type="WATER", use_type="RESIDENTIAL",
                               meter_size="FIVE_EIGHTH", eru_factor=1.0,
                               tap_install_fee_cents=150000, assessment_basis="REDEVELOPMENT",
                               prior_credit_eru=1.0, parcel_id="APN-RD")
    assert app["capacity_fee_cents"] == 0
