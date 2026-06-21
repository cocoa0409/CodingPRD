"""Corner calculation results: wind/hail deductible floor, exclusion negative
delta, wildfire surcharge floor at 40, and the estimate computed read.
Queue B — sections calculations and endpoints.
"""
import pytest

from test_helpers import (
    validate_success,
    TEST_USERS,
    factories as f,
    fixtures as fx,
)

AGENT = TEST_USERS["agent_headers"]
UW = TEST_USERS["underwriter_headers"]


def test_wind_hail_deductible_floor_applies(api):
    """PRD §3.4: "The raw deductible is the requested Coverage A multiplied by the
    deductible percent divided by 100; the stored amount is the greater of that raw
    figure and a 2,500 dollar minimum floor, rounded half up to two decimal places."

    Design: Corner/calculations/wind_hail_deductible_floor_applies
    """
    prop = fx.create_property(street_address="25 Floor St", square_footage=1600, roof_age_years=4)
    fx.commit_estimate(prop["id"], "COMPONENT")
    fx.create_risk_assessment(
        prop["id"], wildfire_fuel_density=30, slope_grade_pct=20,
        defensible_space_ft=150, flood_zone="X", distance_to_coast_mi=60,
    )
    app = fx.create_application(prop["id"], 220000, wind_hail_deductible_pct=1)
    app = fx.submit_application(app["id"])
    quote = fx.get_quote_for_application(app["id"])
    # 220000 * 1/100 = 2200 -> floored to MIN_DEDUCTIBLE 2500
    assert quote["wind_hail_deductible_amount"] == 2500.00, (
        f"Expected 2500.00 floored, got {quote['wind_hail_deductible_amount']}"
    )


def test_exclusion_endorsement_negative_delta(api):
    """PRD §3.5: "For an exclusion, the delta is negative: the negation of a flat
    per-peril credit — 60 for `WATER_BACKUP`, 45 for `SCREENED_ENCLOSURE`, 80 for
    `ORDINANCE_LAW`, 140 for `EARTH_MOVEMENT`, and 70 for `MOLD` — with that credit
    rounded half up to two decimal places before negation."

    Design: Corner/calculations/exclusion_endorsement_negative_delta
    """
    prop = fx.create_property(street_address="26 Excl St")
    app = fx.create_application(prop["id"], 300000)
    e1 = fx.create_endorsement(app["id"], "EXCLUSION", "ORDINANCE_LAW")
    attached = validate_success(api.attach_endorsement(e1["id"], AGENT))
    assert attached["status"] == "PENDING"
    assert attached["premium_delta"] == -80.00, (
        f"ORDINANCE_LAW exclusion credit 80 -> delta -80.00, got {attached['premium_delta']}"
    )


def test_wildfire_surcharge_only_above_40(api):
    """PRD §3.4: "The wildfire multiplier is one plus five thousandths for each point
    by which the wildfire score exceeds 40, applying no surcharge at or below 40 —
    formally, it is one plus five thousandths times the greater of zero and the amount
    the wildfire score exceeds 40, using whichever of the property's wildfire score,
    provisional or final, is current at quote time."

    Design: Corner/calculations/wildfire_surcharge_only_above_40
    """
    # FINAL wildfire_score 20 (<= 40): no surcharge. coverage 300000, X, TIER_1, 2%.
    prop = fx.create_property(street_address="27 NoSur St")
    fx.commit_estimate(prop["id"], "COMPONENT")
    ra = fx.create_risk_assessment(
        prop["id"], wildfire_fuel_density=60, slope_grade_pct=40,
        defensible_space_ft=100, flood_zone="X", distance_to_coast_mi=60,
    )
    fx.setup_passed_inspection(prop["id"], window_start=1751800000, window_end=1751803600)
    ra_final = fx.get_risk_assessment(ra["id"])
    assert ra_final["score_stage"] == "FINAL" and ra_final["wildfire_score"] == 20
    app = fx.create_application(prop["id"], 300000, wind_hail_deductible_pct=2)
    app = fx.submit_application(app["id"])
    quote = fx.get_quote_for_application(app["id"])
    assert quote["base_premium"] == 997.50, (
        f"FINAL wildfire 20 <= 40 -> wf_mult 1.0 -> base 997.50, got {quote['base_premium']}"
    )


def test_estimate_replacement_cost_computed_read(api):
    """PRD §3.1: "Committing either estimate sets `replacement_cost`, sets
    `estimate_variant`, and resets `total_insured_value` to the new `replacement_cost`."

    Design: Corner/endpoints/estimate_replacement_cost_computed_read
    """
    prop = fx.create_property(street_address="32 Calc St")
    data = validate_success(
        api.estimate_replacement_cost(prop["id"], f.estimate_payload("COMPONENT"), AGENT)
    )
    assert data["replacement_cost"] == 274200.00
    assert data["total_insured_value"] == 274200.00
    assert data["estimate_variant"] == "COMPONENT"
