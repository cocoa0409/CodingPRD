"""The four-step incident cost calculation.

Assessing the notification dimension prices the whole case at once: tier,
deadline, gross, surcharge, indemnity credit and net.
"""

from test_helpers import (
    assert_cents,
    assert_instant_equals,
    assessed_incident,
    set_clock,
    vendor_operated_active_asset,
)

GATEKEEPER = {
    "name": "GateKeeper Bio",
    "sells_biometric_data": True,
    "subprocessor_count": 4,
    "deletion_sla_days": 30,
    "subprocessor_disclosure_complete": True,
}


def _incident_on_a_vendor_operated_point(api):
    ctx = vendor_operated_active_asset(
        api,
        vendor_overrides=GATEKEEPER,
        attestation_status="RECEIVED",
        contract_status="EXECUTED",
        activation_clock=None,
    )
    set_clock(api, "2026-09-01T00:00:00Z")
    incident = assessed_incident(
        api,
        ctx["program_id"],
        [ctx["asset_id"]],
        exposure_vector="MISCONFIGURED_EXPORT",
        exposed_subject_count=45,
        translation_locale_count=2,
    )
    return ctx, incident


def test_gross_is_priced_per_subject_and_per_locale_and_the_surcharge_reads_that_gross(api):
    """45 exposed subjects and 2 locales gross 49,125 cents and carry no surcharge.

    PRD §3.8: "**Step two, the regulator surcharge**, keyed on the pre-credit
    gross and never on the net: `regulator_surcharge_cents` is zero when the
    gross is below 50,000 cents (US$500.00); it is 25,000 cents (US$250.00) when
    the gross is at least 50,000 cents and below 150,000 cents (US$1,500.00); and
    it is 75,000 cents (US$750.00) when the gross is at least 150,000 cents."

    The gross is 45 x 425 + 2 x 15,000 = 49,125 cents, which sits 875 cents below
    the first surcharge floor, so no surcharge is due. A fingerprint point with
    45 exposed individuals is `TIER_2`, so the deadline is 45 days after the
    2026-09-01 discovery.

    Design: Difficulty/combinatorial_formula/incident_cost_pins_surcharge_on_gross_and_floors_the_credit
    """
    _ctx, incident = _incident_on_a_vendor_operated_point(api)

    assert_instant_equals(incident["discovered_at"], "2026-09-01T00:00:00.000Z", "discovered_at")
    assert incident["heightened_tier"] == "TIER_2"
    assert_instant_equals(incident["notification_due_at"], "2026-10-16T00:00:00.000Z", "notification_due_at")
    assert_cents(incident["gross_notice_cents"], 49125, "gross_notice_cents")
    assert_cents(incident["regulator_surcharge_cents"], 0, "regulator_surcharge_cents")
    assert incident["notification_status"] == "ASSESSED"
    assert incident["containment_status"] == "DETECTED", "assessment does not touch containment"


def test_indemnity_credit_takes_the_truncated_half_of_an_odd_gross(api):
    """Half of 49,125 cents is credited as 24,562, leaving a net of 24,563.

    PRD §3.8: "`vendor_indemnity_credit_cents` is the smaller of that pool and
    half of the pre-surcharge gross, where the half is **truncated toward zero**
    rather than rounded — an odd gross therefore yields the lower cent."

    The single executed contract pledges 5,000,000 cents of indemnity, so the
    pool is far larger than half the gross; half of 49,125 is 24,562.5, which
    truncates to 24,562, and the net is 49,125 + 0 - 24,562 = 24,563.

    Design: Difficulty/combinatorial_formula/incident_cost_pins_surcharge_on_gross_and_floors_the_credit
    """
    _ctx, incident = _incident_on_a_vendor_operated_point(api)

    assert_cents(incident["gross_notice_cents"], 49125, "gross_notice_cents")
    assert_cents(incident["vendor_indemnity_credit_cents"], 24562, "vendor_indemnity_credit_cents")
    assert_cents(incident["net_incident_cost_cents"], 24563, "net_incident_cost_cents")
    assert (
        incident["net_incident_cost_cents"]
        == incident["gross_notice_cents"]
        + incident["regulator_surcharge_cents"]
        - incident["vendor_indemnity_credit_cents"]
    ), "the net is the gross plus the surcharge minus the credit"
