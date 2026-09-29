"""Two calculations that answer differently depending on the declared variant."""

from test_helpers import fixtures as fx
from test_helpers.assertions import (
    assert_decimal_equals,
    assert_field_values,
    assert_unchanged,
)

# The fourth report is unverified and carries a different hazard code, which is
# what makes the two analysis bases diverge on identical underlying data.
VERIFIED_BURN_REPORTS = (
    {
        "report_channel": "MEDICAL_EXAMINER",
        "incident_date": "2026-01-12T00:00:00Z",
        "narrative": (
            "Base plate weld failed; second-degree burn, consumer hospitalised "
            "overnight."
        ),
        "injury_class": "HOSPITALIZATION",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "RETAILER",
        "incident_date": "2026-01-20T00:00:00Z",
        "narrative": (
            "Store return: unit overheated and scorched the counter; consumer "
            "treated at urgent care."
        ),
        "injury_class": "MEDICAL_TREATMENT",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
    {
        "report_channel": "CONSUMER_HOTLINE",
        "incident_date": "2026-02-02T00:00:00Z",
        "narrative": (
            "Hotline report: minor burn to thumb, treated with first aid at home."
        ),
        "injury_class": "FIRST_AID",
        "hazard_code": "BURN",
        "injury_verified": True,
    },
)

UNVERIFIED_LACERATION_REPORT = {
    "report_channel": "WEB_FORM",
    "incident_date": "2026-02-10T00:00:00Z",
    "narrative": "Web form: small cut on the housing edge, no medical care sought.",
    "injury_class": "FIRST_AID",
    "hazard_code": "LACERATION",
    "injury_verified": False,
}

FOUR_REPORTS = VERIFIED_BURN_REPORTS + (UNVERIFIED_LACERATION_REPORT,)

ANALYSIS_WINDOW = {
    "window_start": "2026-01-01T00:00:00Z",
    "window_end": "2026-02-28T00:00:00Z",
}


def _four_report_model(api):
    """A hundred-unit model carrying three verified burns and one unverified cut."""
    fx.set_clock(api, "2026-03-01T00:00:00Z")
    model = fx.create_product_model(
        api, model_code="TOAST-X1", units_distributed=100, units_registered=60
    )
    incidents = [
        fx.classified_incident(api, model["id"], **spec) for spec in FOUR_REPORTS
    ]
    return model, incidents


class TestHazardPatternAnalysisBasisVariants:
    """The same four incidents under the preliminary and the final basis."""

    def test_preliminary_basis_drops_the_unverified_report_from_every_figure(self, api):
        """Under PRELIMINARY the unverified report contributes nothing at all.

        The contract states: "Under `PRELIMINARY` — the fast triage pass an
        analyst runs while field verification is still outstanding — the set is
        narrowed to incidents whose `injury_verified` is true; unverified reports
        are dropped entirely and contribute nothing to the incident count,
        nothing to the severity sum, and, critically, nothing to the hazard tally
        that decides the dominant code and the concentration ratio."

        Design: Difficulty/dual_variant_calc/pattern_risk_index_preliminary_versus_final_on_identical_incidents
        """
        model, incidents = _four_report_model(api)

        assert_decimal_equals(incidents[0]["severity_weight"], "30.00")
        assert_decimal_equals(incidents[1]["severity_weight"], "9.60")
        assert_decimal_equals(incidents[2]["severity_weight"], "3.00")
        assert_decimal_equals(incidents[3]["severity_weight"], "1.50")

        model = fx.get_product_model(api, model["id"])
        preliminary = fx.create_pattern(
            api,
            model["id"],
            model["version"],
            analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )

        assert_field_values(
            preliminary,
            analysis_basis="PRELIMINARY",
            incident_count=3,
            dominant_hazard_code="BURN",
        )
        assert_decimal_equals(preliminary["severity_sum"], "42.60")
        assert_decimal_equals(preliminary["concentration_ratio"], "1.0000", places=4)
        assert_decimal_equals(preliminary["exposure_per_10k"], "1.0000", places=4)
        assert_decimal_equals(preliminary["risk_index"], "63.90")

    def test_final_basis_admits_the_unverified_report_and_the_dilution_dominates(
        self, api
    ):
        """Under FINAL the extra row raises the sum but dilutes the ratio.

        The contract states: "Under `FINAL` — the closing pass filed with the
        reportability evaluation — the set widens to every qualifying incident
        regardless of `injury_verified`; unverified rows enter at their
        already-halved `severity_weight`, which raises the severity sum but can
        dilute the concentration ratio whenever the additional rows carry a
        different hazard code." Because "nearly every consequential figure — a
        severity weight, a risk index, a lateness surcharge, a penalty
        assessment — is computed once at a named moment and frozen, so that a
        later change of circumstances never silently rewrites history", the
        earlier analysis keeps its own answer.

        Design: Difficulty/dual_variant_calc/pattern_risk_index_preliminary_versus_final_on_identical_incidents
        """
        model, _incidents = _four_report_model(api)

        model = fx.get_product_model(api, model["id"])
        preliminary = fx.create_pattern(
            api,
            model["id"],
            model["version"],
            analysis_basis="PRELIMINARY",
            **ANALYSIS_WINDOW,
        )

        model = fx.get_product_model(api, model["id"])
        final = fx.create_pattern(
            api,
            model["id"],
            model["version"],
            analysis_basis="FINAL",
            **ANALYSIS_WINDOW,
        )

        assert_field_values(
            final,
            analysis_basis="FINAL",
            incident_count=4,
            dominant_hazard_code="BURN",
            pattern_confirmed=True,
        )
        assert_decimal_equals(final["severity_sum"], "44.10")
        assert_decimal_equals(final["concentration_ratio"], "0.7500", places=4)
        assert_decimal_equals(final["exposure_per_10k"], "1.0000", places=4)
        assert_decimal_equals(final["risk_index"], "55.13")

        assert final["risk_index"] != preliminary["risk_index"], (
            "the two bases must not agree on identical incident data"
        )

        preliminary_after = fx.get_pattern(api, preliminary["id"])
        assert_unchanged(
            preliminary,
            preliminary_after,
            "incident_count",
            "severity_sum",
            "concentration_ratio",
            "risk_index",
        )


class TestEffectivenessRateBasisVariants:
    """One frozen unit ledger read against two different denominators."""

    def _monitoring_recall_with_thirty_units_corrected(self, api):
        """A monitoring recall whose ledger stands at 30 of 100 units corrected."""
        env = fx.monitoring_recall_env(api)
        claim = fx.fulfilled_claim(
            api,
            env["recall_id"],
            consumer_ref="CR-1001",
            remedy_type="REFUND",
            quantity=30,
            unit_price_cents=4999,
            shipping_cents_per_unit=899,
        )
        env["claim"] = claim
        return env

    def test_units_basis_divides_the_ledger_by_the_units_in_commerce(self, api):
        """The units basis reports 30 of 100 units in commerce as 30.00 percent.

        The contract states: "On the `UNITS_BASIS` variant the denominator is
        the recall's `units_in_commerce`, that is every unit believed to be in
        consumer hands; this is the regulator-facing correction rate, and it is
        the variant that always drives `effectiveness_flag`."

        Design: Difficulty/dual_variant_calc/effectiveness_rate_units_basis_versus_participation_basis_same_ledger
        """
        env = self._monitoring_recall_with_thirty_units_corrected(api)

        assert env["claim"]["reimbursement_total_cents"] == 190200
        recall = fx.get_recall(api, env["recall_id"])
        assert_field_values(recall, units_corrected=30, units_outstanding=70)

        fx.set_clock(api, "2026-05-14T00:00:00Z")
        first = fx.submitted_progress_report(
            api,
            env["recall_id"],
            period_start="2026-03-13T00:00:00Z",
            period_end="2026-04-12T00:00:00Z",
            effectiveness_basis="UNITS_BASIS",
        )

        assert_field_values(
            first,
            effectiveness_basis="UNITS_BASIS",
            assessment="ON_TRACK",
            units_corrected_in_period=30,
            cumulative_units_corrected=30,
        )
        assert_decimal_equals(first["effectiveness_rate"], "30.00")

    def test_participation_basis_divides_the_same_ledger_by_units_registered(
        self, api
    ):
        """The participation basis reports the same 30 units as 50.00 percent.

        The contract states: "On the `PARTICIPATION_BASIS` variant the
        denominator is the product model's `units_registered`, floored at 1 so
        that a product with no registrations never divides by zero; this is the
        variant a firm with registration-card coverage uses to report against
        the population it can actually reach."

        Design: Difficulty/dual_variant_calc/effectiveness_rate_units_basis_versus_participation_basis_same_ledger
        """
        env = self._monitoring_recall_with_thirty_units_corrected(api)

        fx.set_clock(api, "2026-05-14T00:00:00Z")
        first = fx.submitted_progress_report(
            api,
            env["recall_id"],
            period_start="2026-03-13T00:00:00Z",
            period_end="2026-04-12T00:00:00Z",
            effectiveness_basis="UNITS_BASIS",
        )
        second = fx.submitted_progress_report(
            api,
            env["recall_id"],
            period_start="2026-04-13T00:00:00Z",
            period_end="2026-05-13T00:00:00Z",
            effectiveness_basis="PARTICIPATION_BASIS",
        )

        assert_field_values(
            second,
            effectiveness_basis="PARTICIPATION_BASIS",
            assessment="ON_TRACK",
            units_corrected_in_period=0,
            cumulative_units_corrected=30,
        )
        assert_decimal_equals(second["effectiveness_rate"], "50.00")
        assert second["effectiveness_rate"] != first["effectiveness_rate"], (
            "the two bases must not agree on an identical units_corrected"
        )
