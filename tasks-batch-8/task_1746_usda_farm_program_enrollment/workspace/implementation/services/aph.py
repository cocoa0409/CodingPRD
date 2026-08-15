"""APH yield calculation (SCAFFOLD §1.3 aph_yield_calculation; PRD §3.5).

Weighted average over the trailing 5 years of observations ordered by
crop_year ascending. Effective yield per observation:
  - actual value, when present and not disaster-substituted
  - 0.65 * T-yield, when disaster-substituted
  - plug yield, when actual value is null (no evidence)

Result rounds half-up to 1 decimal place.
"""

from decimal import Decimal, ROUND_HALF_UP

import db

T_YIELD = {
    "CORN": Decimal("180"),
    "SOYBN": Decimal("50"),
    "WHEAT": Decimal("65"),
}

PLUG_YIELD = {
    "CORN": Decimal("135"),
    "SOYBN": Decimal("37"),
    "WHEAT": Decimal("49"),
}

DISASTER_SUBSTITUTION_FACTOR = Decimal("0.65")
OBSERVATION_WINDOW_YEARS = 5


def compute_aph(yield_record):
    """Recompute and store aph_yield_bu_per_acre on the yield record."""
    commodity = yield_record["commodity"]
    t_yield = T_YIELD.get(commodity)
    plug = PLUG_YIELD.get(commodity)

    observations = [
        o for o in db.yield_observations.values()
        if o["yield_record_id"] == yield_record["id"]
    ]
    # Sort is stable over dict insertion order, so for a given crop_year the
    # most recently appended observation wins below (dict overwrite). This is
    # how a plug year (null actual) is replaced by an observed value for the
    # same year — PRD §3.5: "a certified APH replaces plugs with observed
    # values".
    observations.sort(key=lambda o: (o["crop_year"], o["created_at"]))
    latest_by_year = {}
    for obs in observations:
        latest_by_year[obs["crop_year"]] = obs
    # One effective yield per crop year; trailing 5 years only.
    years = sorted(latest_by_year)[-OBSERVATION_WINDOW_YEARS:]
    observations = [latest_by_year[y] for y in years]

    total = Decimal("0")
    for obs in observations:
        actual = obs.get("actual_yield_bu_per_acre")
        if obs.get("is_disaster_substituted") and t_yield is not None:
            effective = DISASTER_SUBSTITUTION_FACTOR * t_yield
        elif actual is None:
            effective = plug if plug is not None else Decimal("0")
        else:
            effective = Decimal(str(actual))
        total += effective

    aph = (total / Decimal(str(OBSERVATION_WINDOW_YEARS))).quantize(
        Decimal("0.1"), rounding=ROUND_HALF_UP
    )
    yield_record["aph_yield_bu_per_acre"] = float(aph)
    return yield_record["aph_yield_bu_per_acre"]
