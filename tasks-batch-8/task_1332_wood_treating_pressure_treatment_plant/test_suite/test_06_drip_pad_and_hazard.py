"""Drip-pad containment: liability cascade, surcharge threshold, dwell gate
at tagging (PRD §2.5, §3.8)."""
import pytest

from test_helpers import (
    ApiErrorId,
    BREACH_COMPLIANCE_PENALTY,
    CRITICAL_BREACH_SURCHARGE_CENTS,
    DRIP_ENTER,
    DRIP_EXIT_OK,
    DRIP_EXIT_SHORT,
    PER_LITER_RATE_CENTS,
    TEST_USERS,
    get_charge,
    get_plant,
    log_drip_pad,
    record_assay_for_outcome,
    setup_assayed_charge,
    setup_cycle_complete_charge,
    setup_shop,
    validate_error,
    validate_success,
)

OP = TEST_USERS["plant_operator_headers"]


class TestBreachCascade:
    def test_drip_pad_breach_cascades_to_liability_score_flag(self, api):
        """PRD §3.8: "the log's `liability_cents` is the `drip_volume_liters`
        multiplied by 250 cents per liter ($2.50/L), rounded half-up to whole
        cents, and that amount is added to the plant's
        `hazardous_waste_liability_cents` while the charge's
        `hazard_containment_flag` is set true. When the spilled
        `drip_volume_liters` exceeds 50 liters, a 250000-cent surcharge
        ($2,500) is added on top and the plant's `compliance_score` drops by
        50, never below zero."

        Design: Difficulty/transitive_cascade/drip_pad_breach_cascades_to_liability_score_flag
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, _cycle = setup_cycle_complete_charge(shop)

        # 75.0 L breach: 75 * 250 = 18750, plus the 250000 surcharge.
        log = log_drip_pad(plant_id, charge["id"], drip_volume_liters=75.0,
                           containment_breach=True)
        assert log["liability_cents"] == 18750 + CRITICAL_BREACH_SURCHARGE_CENTS
        assert log["containment_breach"] is True

        plant = get_plant(plant_id)
        assert plant["hazardous_waste_liability_cents"] == 268750
        assert plant["compliance_score"] == 1000 - BREACH_COMPLIANCE_PENALTY

        flagged = get_charge(plant_id, charge["id"])
        assert flagged["hazard_containment_flag"] is True

    def test_breach_just_over_threshold_adds_surcharge(self, api):
        """PRD §3.8: "When the spilled `drip_volume_liters` exceeds 50 liters,
        a 250000-cent surcharge ($2,500) is added on top and the plant's
        `compliance_score` drops by 50, never below zero."

        Design: Difficulty/transitive_cascade/drip_pad_breach_cascades_to_liability_score_flag
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, _cycle = setup_cycle_complete_charge(shop)

        # 50.1 L strictly exceeds the 50 L threshold.
        log = log_drip_pad(plant_id, charge["id"], drip_volume_liters=50.1,
                           containment_breach=True)
        expected = int(50.1 * PER_LITER_RATE_CENTS) + CRITICAL_BREACH_SURCHARGE_CENTS
        assert log["liability_cents"] == expected  # 12525 + 250000 = 262525

        plant = get_plant(plant_id)
        assert plant["hazardous_waste_liability_cents"] == expected
        assert plant["compliance_score"] == 1000 - BREACH_COMPLIANCE_PENALTY
        assert get_charge(plant_id, charge["id"])["hazard_containment_flag"] is True

    def test_hazard_liability_threshold_boundary(self, api):
        """PRD §3.8: "the log's `liability_cents` is the `drip_volume_liters`
        multiplied by 250 cents per liter ($2.50/L), rounded half-up to whole
        cents".
        PRD §3.8: "When the spilled `drip_volume_liters` exceeds 50 liters, a
        250000-cent surcharge ($2,500) is added on top" — exactly 50 liters
        does not exceed the threshold, so no surcharge applies.

        Design: Corner/calculations/hazard_liability_threshold_boundary
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, _cycle = setup_cycle_complete_charge(shop)

        log = log_drip_pad(plant_id, charge["id"], drip_volume_liters=50.0,
                           containment_breach=True)
        # Exactly at the threshold: 50 * 250 = 12500, no surcharge, no score hit.
        assert log["liability_cents"] == 12500

        plant = get_plant(plant_id)
        assert plant["hazardous_waste_liability_cents"] == 12500
        assert plant["compliance_score"] == 1000


class TestDripDwellGate:
    def test_drip_dwell_too_short_returns_422(self, api):
        """PRD §3.8: "the dwell itself, `exited_pad_at` minus `entered_pad_at`,
        must be at least 24 hours, failing with `ERR_DRIP_DWELL_TOO_SHORT`
        (422) when shorter."

        Design: Corner/validations/drip_dwell_too_short_returns_422
        """
        shop = setup_shop()
        plant_id = shop["plant"]["id"]
        charge, _cycle, assay = setup_assayed_charge(shop, outcome="PASS")
        assert charge["status"] == "ASSAYED_PASS"

        # 12-hour dwell: below the 24-hour minimum.
        log_drip_pad(plant_id, charge["id"], entered_pad_at=DRIP_ENTER,
                     exited_pad_at=DRIP_EXIT_SHORT)

        resp = api.tag_charge(plant_id, charge["id"], OP)
        validate_error(resp, ApiErrorId.ERR_DRIP_DWELL_TOO_SHORT.value)
