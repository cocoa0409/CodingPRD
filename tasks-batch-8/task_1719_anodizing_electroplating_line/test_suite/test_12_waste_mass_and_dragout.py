"""Dragout depletion, month bucketing/reset, and cumulative cap boundaries."""
from test_helpers import (
    ApiErrorId,
    CHEM,
    EHS,
    OP,
    complete_load_run,
    create_compat_rule,
    create_customer,
    create_permit,
    create_titrated_bath,
    get_bath,
    get_permit,
    record_sample,
    setup_awaiting_inspection,
    start_load_run,
    validate_error,
)
from test_helpers.api_client import api_client


def test_dragout_depletion_visible_immediately():
    """PRD §3.5: "Dragout depletion then lowers the bath's chemistry: the new
    `current_concentration_g_l` is the current value minus the load's
    `surface_area_dm2` multiplied by 0.0008 grams per liter per square decimeter,
    floored at zero, rounded half-up to three decimal places."
    PRD §2.9: "all of their effects commit atomically within the request."

    Design: Corner/calculations/dragout_depletion_visible_immediately
    """
    customer = create_customer(company_name="Drag Co")
    create_compat_rule()
    bath = create_titrated_bath(bath_code="ANO-D2", routing_modes_supported=["BARREL"])
    assert bath["current_concentration_g_l"] == 5.0
    wo = setup_awaiting_inspection(customer["id"], bath["id"], part_number="PN-D2")[0]
    # Completing a 25 dm2 load depletes exactly 25 x 0.0008 = 0.020 g/L.
    detail = get_bath(bath["id"])
    assert detail["current_concentration_g_l"] == 4.98, (
        f"Concentration after completion: expected 4.98, "
        f"got {detail['current_concentration_g_l']}"
    )
    # Reservation moved to used atomically (25 dm2 x 1.5 x 40 / 60 = 25.0 Ah).
    assert detail["amp_hour_used"] == 25.0
    assert detail["amp_hour_reserved"] == 0.0


def test_month_reset_and_regression():
    """PRD §3.8: "Month bucketing follows the calendar month of `sampled_at`: when the
    permit's `current_month` is null or the sample's month is later, `current_month`
    advances to the sample's month and `cumulative_mass_g` resets to just this sample's
    masses; when the sample's month equals `current_month`, each analyte's rounded mass
    accumulates into the running totals; when the sample's month is earlier, the sample
    is rejected with `ERR_SAMPLE_MONTH_REGRESSION`."

    Design: Corner/calculations/month_reset_and_regression
    """
    permit = create_permit(outfall_code="OUTFALL-R", effective_from="2026-08-01",
                           effective_to="2026-12-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 10.0,
                                    "monthly_mass_cap_g": 1000.0}])
    # August sample: 5.0 mg/L x 1000 L / 1000 = 5.0 g.
    record_sample(permit["id"], flow_liters=1000,
                  readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 5.0}],
                  sampled_at="2026-08-10T00:00:00Z")
    # September sample resets the cumulative to just its own mass.
    s2 = record_sample(permit["id"], flow_liters=1000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 5.0}],
                       sampled_at="2026-09-05T00:00:00Z")
    assert s2["is_exceedance"] is False
    detail = get_permit(permit["id"])
    assert detail["current_month"] == "2026-09"
    assert detail["cumulative_mass_g"]["NICKEL"] == 5.0
    # An August-dated sample after the month advanced is rejected.
    resp = api_client.create_waste_sample(
        permit["id"],
        {"flow_liters": 1000,
         "readings": [{"analyte_code": "NICKEL", "concentration_mg_l": 5.0}],
         "sampled_at": "2026-08-20T00:00:00Z"},
        EHS,
    )
    validate_error(resp, ApiErrorId.ERR_SAMPLE_MONTH_REGRESSION)


def test_cumulative_cap_equality_compliant():
    """PRD §3.8: "A sample is an exceedance — `is_exceedance` true — when any reading's
    concentration is strictly greater than its limit's `max_concentration_mg_l`, or
    when any analyte's cumulative mass after adding the sample is strictly greater than
    its `monthly_mass_cap_g`; equality on either measure is compliant."

    Design: Corner/calculations/cumulative_cap_equality_compliant
    """
    permit = create_permit(outfall_code="OUTFALL-C", effective_from="2026-08-01",
                           effective_to="2026-08-31",
                           limits=[{"analyte_code": "NICKEL", "max_concentration_mg_l": 5.0,
                                    "monthly_mass_cap_g": 30.0}])
    # 2.0 mg/L x 10000 L / 1000 = 20.0 g
    s1 = record_sample(permit["id"], flow_liters=10000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.0}])
    assert s1["is_exceedance"] is False
    # 2.0 x 5000 / 1000 = 10.0 g -> cumulative exactly 30.0 == cap: compliant.
    s2 = record_sample(permit["id"], flow_liters=5000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.0}])
    assert s2["is_exceedance"] is False
    detail = get_permit(permit["id"])
    assert detail["cumulative_mass_g"]["NICKEL"] == 30.0
    assert detail["status"] == "ACTIVE"
    # Next 2.0 g sample pushes cumulative to 32.0 > 30.0: exceedance.
    s3 = record_sample(permit["id"], flow_liters=1000,
                       readings=[{"analyte_code": "NICKEL", "concentration_mg_l": 2.0}])
    assert s3["is_exceedance"] is True
    assert get_permit(permit["id"])["status"] == "EXCEEDED"
