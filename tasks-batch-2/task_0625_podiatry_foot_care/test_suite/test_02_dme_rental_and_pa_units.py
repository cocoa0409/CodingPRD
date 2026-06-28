"""DME rent-to-own charges, PA unit draw-downs, auto-exhaustion, and the
dispense/return conservation invariant.
"""
import pytest
from test_helpers import (
    api_client, get_success_data, validate_success, validate_error,
    assert_dme_dispense, assert_prior_authorization, assert_pa_units_invariant,
    ApiErrorId, TEST_USERS,
    setup_dme_pa_and_encounter, setup_rental_accumulated_to_cap_minus_one,
    dispense_dme,
)

FRONTDESK = TEST_USERS["front_desk_headers"]


# ─── dual_variant_calc / dme_rental_cap_vs_purchase_full_charge ─────────────
class TestDmeRentToOwnDualVariant:
    """PURCHASE charges full price; a RENTAL whose cumulative reached the cap is
    charged only the remaining-to-cap amount."""

    def test_purchase_charges_full_purchase_price(self, api):
        """PRD §3.8: "For a `PURCHASE`, `this_period_charge_cents` and
        `cumulative_rental_paid_cents` are both the full `purchase_price_cents`."

        Design: Difficulty/dual_variant_calc/dme_rental_cap_vs_purchase_full_charge
        """
        # Five prior RENTAL periods at 5000 -> cumulative 25000 (cap 30000).
        pa, enc, pa_version = setup_rental_accumulated_to_cap_minus_one(
            monthly_rental=5000, purchase_price=30000, prior_rental_periods=5)
        disp = dispense_dme(pa["id"], enc["id"], pa_version,
                            hcpcs_code="L4360", acquisition_mode="PURCHASE", units=1,
                            purchase_price_cents=30000)
        assert_dme_dispense(disp)
        assert disp["this_period_charge_cents"] == 30000
        assert disp["cumulative_rental_paid_cents"] == 30000

    def test_rental_charged_only_remaining_to_cap(self, api):
        """PRD §3.8: "the remaining amount to the cap is `purchase_price_cents`
        minus that prior cumulative. If the remaining amount to the cap is zero
        or less, `this_period_charge_cents` is 0; otherwise it is the lesser of
        `monthly_rental_cents` and the remaining amount to the cap."

        Design: Difficulty/dual_variant_calc/dme_rental_cap_vs_purchase_full_charge
        """
        # Five prior RENTAL periods at 5000 -> cumulative 25000; remaining-to-cap 5000.
        pa, enc, pa_version = setup_rental_accumulated_to_cap_minus_one(
            monthly_rental=5000, purchase_price=30000, prior_rental_periods=5)
        disp = dispense_dme(pa["id"], enc["id"], pa_version,
                            hcpcs_code="L4360", acquisition_mode="RENTAL", units=1,
                            purchase_price_cents=30000, monthly_rental_cents=5000)
        # min(5000, remaining 5000) = 5000; cumulative -> 30000 (exactly the cap).
        assert disp["this_period_charge_cents"] == 5000
        assert disp["cumulative_rental_paid_cents"] == 30000


# ─── calculations / dme_purchase_charges_full_price ────────────────────────
def test_first_purchase_charges_full_price_no_history(api):
    """PRD §3.8: "For a `PURCHASE`, `this_period_charge_cents` and
    `cumulative_rental_paid_cents` are both the full `purchase_price_cents`."

    Design: Corner/calculations/dme_purchase_charges_full_price
    """
    practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
        pa_overrides={"service_category": "DME", "hcpcs_code": "L4360", "authorized_units": 2})
    disp = dispense_dme(pa["id"], enc["id"], pa["version"],
                        hcpcs_code="L4360", acquisition_mode="PURCHASE", units=1,
                        purchase_price_cents=15000)
    assert disp["this_period_charge_cents"] == 15000


# ─── boundary_precision_check / pa_remaining_units_hits_exactly_zero_auto_exhausted ─
class TestPaAutoExhaustionBoundary:
    """Drawing remaining_units to exactly 0 auto-transitions APPROVED -> EXHAUSTED."""

    def test_remaining_units_reaches_zero(self, api):
        """PRD §3.6: "if `remaining_units` reaches exactly 0, the authorization
        automatically transitions `APPROVED → EXHAUSTED` and accepts no further
        draws."

        Design: Difficulty/boundary_precision_check/pa_remaining_units_hits_exactly_zero_auto_exhausted
        """
        practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
            pa_overrides={"service_category": "DME", "hcpcs_code": "L4360",
                          "authorized_units": 2})
        dispense_dme(pa["id"], enc["id"], pa["version"],
                     hcpcs_code="L4360", acquisition_mode="PURCHASE", units=2,
                     purchase_price_cents=15000)
        live = get_success_data(api.get_prior_authorization(pa["id"], FRONTDESK))
        assert live["remaining_units"] == 0

    def test_status_auto_exhausted_at_zero(self, api):
        """PRD §3.6: "if `remaining_units` reaches exactly 0, the authorization
        automatically transitions `APPROVED → EXHAUSTED` and accepts no further
        draws."

        Design: Difficulty/boundary_precision_check/pa_remaining_units_hits_exactly_zero_auto_exhausted
        """
        practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
            pa_overrides={"service_category": "DME", "hcpcs_code": "L4360",
                          "authorized_units": 2})
        dispense_dme(pa["id"], enc["id"], pa["version"],
                     hcpcs_code="L4360", acquisition_mode="PURCHASE", units=2,
                     purchase_price_cents=15000)
        live = get_success_data(api.get_prior_authorization(pa["id"], FRONTDESK))
        assert live["status"] == "EXHAUSTED"
        assert_prior_authorization(live)


# ─── compensating_invariant / dme_dispense_then_return_conserves_pa_units ──
class TestDmeReturnConservesUnits:
    """Dispense (consumed->2, remaining->0, EXHAUSTED) then return restores the
    pool to consumed 0 / remaining 2 / APPROVED with zero drift."""

    def _dispense_two_then_return(self, api):
        practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
            pa_overrides={"service_category": "DME", "hcpcs_code": "L4360",
                          "authorized_units": 2})
        disp = dispense_dme(pa["id"], enc["id"], pa["version"],
                            hcpcs_code="L4360", acquisition_mode="PURCHASE", units=2,
                            purchase_price_cents=15000)
        get_success_data(api.return_dme_dispense(disp["id"], FRONTDESK))
        return get_success_data(api.get_prior_authorization(pa["id"], FRONTDESK))

    def test_units_consumed_and_remaining_restored(self, api):
        """PRD §3.8: "Returning compensates the authorization: the dispense's
        `units` are subtracted from `units_consumed`, `remaining_units` is
        recomputed, the authorization's `version` is incremented, and if the
        authorization had been `EXHAUSTED` and `remaining_units` becomes greater
        than 0 it is revived to `APPROVED`."

        Design: Difficulty/compensating_invariant/dme_dispense_then_return_conserves_pa_units
        """
        live = self._dispense_two_then_return(api)
        assert live["units_consumed"] == 0
        assert live["remaining_units"] == 2
        assert_pa_units_invariant(live)

    def test_status_revived_to_approved(self, api):
        """PRD §3.8: "if the authorization had been `EXHAUSTED` and
        `remaining_units` becomes greater than 0 it is revived to `APPROVED`."

        Design: Difficulty/compensating_invariant/dme_dispense_then_return_conserves_pa_units
        """
        live = self._dispense_two_then_return(api)
        assert live["status"] == "APPROVED"


# ─── cross_cutting / derived_remaining_units_reconciled_after_partial_draw ─
def test_remaining_units_reconciled_after_partial_draw(api):
    """PRD §3.6: "the draw quantity is added to `units_consumed` and
    `remaining_units` is recomputed as `authorized_units` minus
    `units_consumed`"

    Design: Corner/cross_cutting/derived_remaining_units_reconciled_after_partial_draw
    """
    practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
        pa_overrides={"service_category": "DME", "hcpcs_code": "L4360",
                      "authorized_units": 3})
    dispense_dme(pa["id"], enc["id"], pa["version"],
                 hcpcs_code="L4360", acquisition_mode="PURCHASE", units=1,
                 purchase_price_cents=15000)
    live = get_success_data(api.get_prior_authorization(pa["id"], FRONTDESK))
    assert live["units_consumed"] == 1
    assert live["remaining_units"] == 2
    assert live["status"] == "APPROVED"
    assert_pa_units_invariant(live)


# ─── validations / pa_units_exceeded_on_dme_dispense ───────────────────────
def test_dispense_exceeding_remaining_units_rejected(api):
    """PRD §3.6: "A draw whose quantity exceeds the current `remaining_units` is
    rejected with `ERR_PA_UNITS_EXCEEDED`"

    Design: Corner/validations/pa_units_exceeded_on_dme_dispense
    """
    practice, provider, patient, pa, enc = setup_dme_pa_and_encounter(
        pa_overrides={"service_category": "DME", "hcpcs_code": "L4360",
                      "authorized_units": 2})
    from test_helpers import create_dme_dispense_payload
    res = api.create_dme_dispense(
        create_dme_dispense_payload(pa["id"], enc["id"], pa["version"],
                                    hcpcs_code="L4360", acquisition_mode="PURCHASE",
                                    units=3, purchase_price_cents=15000),
        FRONTDESK)
    validate_error(res, ApiErrorId.ERR_PA_UNITS_EXCEEDED.value)
