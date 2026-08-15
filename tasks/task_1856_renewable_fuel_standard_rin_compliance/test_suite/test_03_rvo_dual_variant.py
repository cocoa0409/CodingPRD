"""Provisional vs final RVO variants and posture derivation (PRD §2.6)."""
from test_helpers import (
    CM,
    create_account,
    create_obligation_year_payload,
    create_year,
    set_clock,
    validate_success,
    api_client,
)


class TestRvoProvisionalVsFinal:
    def _setup(self, api, epa_id):
        acct = create_account(epa_registration_id=epa_id)
        yr = create_year(
            acct["id"], year=2026, projected_volume_gal=1000,
            std_cellulosic_pct=10.0, std_biomass_diesel_pct=20.0,
            std_advanced_pct=30.0, std_total_pct=40.0,
        )
        resp = api.close_volume(yr["id"], {"actual_volume_gal": 1200}, CM)
        validate_success(resp)
        return acct, yr

    def test_provisional_rvos_computed_from_projected_volume(self, api):
        """PRD §2.6: "At creation, the provisional variant computes `provisional_rvo_cellulosic_rins`, `provisional_rvo_biomass_diesel_rins`, `provisional_rvo_advanced_rins`, and `provisional_rvo_total_rins`; each equals the projected non-renewable volume multiplied by the corresponding EPA standard percentage divided by one hundred, rounded half-up to a whole RIN."

        Design: Difficulty/dual_variant_calc/rvo_provisional_vs_final_on_obligation_year
        """
        _acct, yr = self._setup(api, "EPA-ACME-1")
        resp = api.get_obligation_year(yr["id"], CM)
        data = validate_success(resp)
        assert data["provisional_rvo_cellulosic_rins"] == 100
        assert data["provisional_rvo_biomass_diesel_rins"] == 200
        assert data["provisional_rvo_advanced_rins"] == 300
        assert data["provisional_rvo_total_rins"] == 400

    def test_final_rvos_computed_from_actual_volume_and_diverge(self, api):
        """PRD §2.6: "When the year's actual volume is later closed, the final variant recomputes the same four quantities from the actual volume and writes them to `final_rvo_cellulosic_rins`, `final_rvo_biomass_diesel_rins`, `final_rvo_advanced_rins`, and `final_rvo_total_rins`"
        PRD §2.6: "Identical inputs would produce identical values under either variant, but projected and actual volumes diverge, so a year's provisional and final obligations generally differ."

        Design: Difficulty/dual_variant_calc/rvo_provisional_vs_final_on_obligation_year
        """
        _acct, yr = self._setup(api, "EPA-ACME-1B")
        resp = api.get_obligation_year(yr["id"], CM)
        data = validate_success(resp)
        assert data["final_rvo_cellulosic_rins"] == 120
        assert data["final_rvo_biomass_diesel_rins"] == 240
        assert data["final_rvo_advanced_rins"] == 360
        assert data["final_rvo_total_rins"] == 480
        assert data["provisional_rvo_total_rins"] != data["final_rvo_total_rins"]


class TestPostureShortfall:
    def test_posture_flips_to_shortfall_after_deadline(self, api):
        """PRD §2.6: "When the year is not satisfied and the logical clock has passed the retirement deadline — 23:59:59 UTC on March 31 of the year following the compliance year — the posture is `SHORTFALL`."
        PRD §2.4: "Advancing the clock is not cosmetic: it fires the vintage-expiry sweep across all active lots (§2.10) and re-derives the compliance posture of every obligation year (§2.6)."

        Design: Corner/calculations/posture_shortfall_after_deadline
        """
        acct = create_account(epa_registration_id="EPA-CALC-6")
        yr = create_year(acct["id"], year=2026, projected_volume_gal=1000)
        set_clock("2027-04-01T00:00:00Z")
        resp = api.get_obligation_year(yr["id"], CM)
        data = validate_success(resp)
        assert data["compliance_posture"] == "SHORTFALL"
