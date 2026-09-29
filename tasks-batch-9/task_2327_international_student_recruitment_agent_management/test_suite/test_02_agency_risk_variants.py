"""The two agency risk figures diverge, and only one of them moves posture.

Three confirmed incidents of different ages are adjudicated against an agency
that has no applications and no documents at all, so the document-quality term
of both figures is exactly zero and the divergence comes purely from the
age-decay window that one variant applies and the other does not.
"""

import pytest

from test_helpers import constants as C
from test_helpers import fixtures as fx
from test_helpers.assertions import assert_risk_profile, assert_score_2dp


@pytest.fixture()
def confirmed_incident_history(client):
    """An agency with three confirmed incidents aged 26, 280 and 440 days."""
    agency = fx.register_agency(
        client,
        legal_name="Meridian Study Abroad",
        home_country_code="VN",
        beneficial_owner_count=1,
        reference_check_count=2,
    )
    fx.set_clock(client, "2027-01-15T00:00:00Z", headers=fx.COMPLIANCE)

    high = fx.file_incident(
        client,
        agency["id"],
        category=C.INCIDENT_MISREPRESENTATION,
        severity=C.SEVERITY_HIGH,
        occurred_on="2026-12-20",
        source=C.SOURCE_AUDIT,
    )
    critical = fx.file_incident(
        client,
        agency["id"],
        category=C.INCIDENT_DISCLOSURE_FAILURE,
        severity=C.SEVERITY_CRITICAL,
        occurred_on="2026-04-10",
        source=C.SOURCE_STUDENT_COMPLAINT,
    )
    medium = fx.file_incident(
        client,
        agency["id"],
        category=C.INCIDENT_MISREPRESENTATION,
        severity=C.SEVERITY_MEDIUM,
        occurred_on="2025-11-01",
        source=C.SOURCE_PARTNER_REPORT,
    )

    for incident in (high, critical, medium):
        fx.resolve_incident(client, incident["id"], C.RESOLUTION_CONFIRM)

    return {"agency_id": agency["id"]}


class TestAgencyRiskVariants:
    def test_rolling_variant_windows_and_decays_where_lifetime_accumulates_in_full(
        self, client, confirmed_incident_history
    ):
        """The same three incidents score 55.00 rolling and 95.00 lifetime.

        "It considers only confirmed incidents whose age — the number of days
        from `occurred_on` to the current logical-clock date — is at most 365."

        "half, a factor of 0.50, for anything older within the 365-day window"

        "`lifetime_risk_score` is the undecayed cumulative figure. It considers
        every confirmed incident with no window at all and applies no decay, so
        each contributes its full severity weight"

        Design: Difficulty/dual_variant_calc/agency_risk_rolling_versus_lifetime_band_divergence
        """
        agency_id = confirmed_incident_history["agency_id"]

        profile = fx.read_risk_profile(client, agency_id)
        assert_risk_profile(
            profile,
            rolling_risk_score=55.00,
            lifetime_risk_score=95.00,
            lifetime_minus_rolling_delta=40.00,
            confirmed_incident_count=3,
            reviewed_document_count=0,
            confirmed_fraud_document_count=0,
            posture_band=C.POSTURE_WATCH,
        )

        agency = fx.read_agency(client, agency_id)
        assert_score_2dp(agency["rolling_risk_score"], 55.00, "rolling_risk_score")
        assert_score_2dp(agency["lifetime_risk_score"], 95.00, "lifetime_risk_score")
        assert agency["confirmed_incident_count"] == 3

    def test_only_the_rolling_variant_drives_posture_and_the_vetting_dimension_is_untouched(
        self, client, confirmed_incident_history
    ):
        """A 95.00 lifetime figure does not reach the suspension band.

        "`rolling_risk_score` is the age-decayed figure and it is the one that
        drives posture."

        "a rolling figure at or above 85.00 targets `SUSPENDED`, at or above
        65.00 but below 85.00 targets `PROBATION`, and at or above 40.00 but
        below 65.00 targets `WATCH`"

        "The two run independently: every combination of the two dimensions is
        reachable except that neither terminal can be left." — adjudication moved
        the integrity dimension while the due-diligence dimension stayed exactly
        where registration left it.

        Design: Difficulty/dual_variant_calc/agency_risk_rolling_versus_lifetime_band_divergence
        """
        agency_id = confirmed_incident_history["agency_id"]

        agency = fx.read_agency(client, agency_id)
        assert agency["compliance_posture"] == C.POSTURE_WATCH, (
            "the 85.00 suspension band must not be applied from the lifetime figure"
        )
        assert agency["vetting_state"] == C.VETTING_DRAFT
