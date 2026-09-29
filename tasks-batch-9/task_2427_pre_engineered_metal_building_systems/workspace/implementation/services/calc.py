"""The eleven calculation rules of SCAFFOLD `calculations` / PRD 3.3, 3.4, 3.6, 3.8, 3.9.

Every rounding here is round-half-up (PRD 2.7); no float arithmetic is used for
any stored quantity.
"""

from decimal import Decimal, ROUND_HALF_UP, getcontext

import constants as C

getcontext().prec = 60


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    """Round half up to `places` decimal places."""
    return D(value).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def money(value):
    """Whole cents, produced by rounding half up to zero decimals."""
    return int(rhu(value, 0))


# ---------------------------------------------------------------- geometry
def configuration_geometry_and_loads(config, jurisdiction):
    """PRD 3.3 -- runs on every lock (DRAFT -> LOCKED and CRITERIA_STALE -> LOCKED)."""
    clear_span = D(config["clear_span_ft"])
    bay_spacing = D(config["bay_spacing_ft"])
    bay_count = D(config["bay_count"])
    eave_height = D(config["eave_height_ft"])
    pitch = D(config["roof_pitch_rise_per_12"])

    building_length = bay_spacing * bay_count
    footprint = clear_span * building_length

    roof_slope_factor = rhu((D(144) + pitch * pitch).sqrt() / D(12), 4)
    # The FOUR-DECIMAL rounded slope factor is the multiplicand, not the raw quotient.
    roof_panel_area = rhu(footprint * roof_slope_factor, 2)
    wall_panel_area = rhu(D(2) * (clear_span + building_length) * eave_height, 2)
    panel_area = rhu(roof_panel_area + wall_panel_area, 2)

    kz = C.EXPOSURE_KZ[jurisdiction["exposure_category"]]
    wind_speed = D(jurisdiction["design_wind_speed_mph"])
    qz = rhu(C.VELOCITY_PRESSURE_COEFF * kz * wind_speed * wind_speed, 4)
    roof_gcp = C.GCP_ROOF_LOW_SLOPE if pitch <= C.LOW_SLOPE_PITCH_MAX else C.GCP_ROOF_STEEP
    gcp = max(C.GCP_WALL, roof_gcp)
    excess_height = eave_height - C.HEIGHT_FACTOR_BASE_FT
    if excess_height < 0:
        excess_height = D(0)
    height_factor = min(C.HEIGHT_FACTOR_CAP, D(1) + excess_height * C.HEIGHT_FACTOR_PER_FT)
    design_wind_pressure = rhu(qz * gcp * height_factor, 2)

    dead_load = rhu(
        C.PANEL_DEAD_PSF[config["panel_profile"]]
        + C.FRAME_DEAD_ALLOWANCE_PSF
        + D(config["insulation_r_value"]) * C.INSULATION_PSF_PER_R,
        2,
    )
    roof_snow_load = rhu(D(jurisdiction["ground_snow_load_psf"]) * C.SNOW_ROOF_FACTOR, 2)

    excess_span = clear_span - C.SPAN_FACTOR_FREE_FT
    if excess_span < 0:
        excess_span = D(0)
    span_factor = D(1) + excess_span * C.SPAN_FACTOR_PER_FT
    estimated_frame_weight = rhu(footprint * C.ESTIMATE_BASE_PSF * span_factor, 2)

    return {
        "building_length_ft": building_length,
        "footprint_sqft": footprint,
        "roof_slope_factor": roof_slope_factor,
        "panel_area_sqft": panel_area,
        "design_wind_pressure_psf": design_wind_pressure,
        "dead_load_psf": dead_load,
        "roof_snow_load_psf": roof_snow_load,
        "estimated_frame_weight_lbs": estimated_frame_weight,
    }


# --------------------------------------------------- load combination family
def design_load_combination_and_required_moment(config, design_variant):
    """PRD 3.6 -- runs at POST /engineering-designs."""
    dead = D(config["dead_load_psf"])
    wind = D(config["design_wind_pressure_psf"])
    snow = D(config["roof_snow_load_psf"])

    if design_variant == "ASD":
        candidates = [
            ("ASD_D_PLUS_S", rhu(dead + snow, 2)),
            ("ASD_D_PLUS_0_6W", rhu(dead + D("0.6") * wind, 2)),
            (
                "ASD_D_PLUS_0_75S_PLUS_0_45W",
                rhu(dead + D("0.75") * snow + D("0.45") * wind, 2),
            ),
        ]
    else:
        candidates = [
            ("LRFD_1_4D", rhu(D("1.4") * dead, 2)),
            ("LRFD_1_2D_PLUS_1_6S", rhu(D("1.2") * dead + D("1.6") * snow, 2)),
            (
                "LRFD_1_2D_PLUS_1_0W_PLUS_0_5S",
                rhu(D("1.2") * dead + D("1.0") * wind + D("0.5") * snow, 2),
            ),
        ]

    # On a tie the candidate appearing earliest in the list order wins.
    governing_combination, governing_load = candidates[0]
    for name, pressure in candidates[1:]:
        if pressure > governing_load:
            governing_combination, governing_load = name, pressure

    bay_spacing = D(config["bay_spacing_ft"])
    clear_span = D(config["clear_span_ft"])
    tributary = rhu(governing_load * bay_spacing / D(1000), 6)
    required_moment = rhu(tributary * clear_span * clear_span / D(8), 2)

    return {
        "governing_combination": governing_combination,
        "governing_load_psf": governing_load,
        "tributary_load_kip_per_ft": tributary,
        "required_moment_kip_ft": required_moment,
    }


# ------------------------------------------------------------ component weight
def component_weights(component_class, length_ft, weight_per_ft, quantity):
    """PINNED rounding order: round the unit weight to 2 dp FIRST, multiply by
    quantity, round that line to 2 dp."""
    if component_class == "CONNECTION_DETAIL":
        return D(0), D(0)
    unit_weight = rhu(D(length_ft) * D(weight_per_ft), 2)
    line_weight = rhu(unit_weight * D(quantity), 2)
    return unit_weight, line_weight


def design_weight_rollup(components):
    """PRD 3.6 -- sum the already-rounded lines, never the raw products."""
    frame_total = D(0)
    shippable_total = D(0)
    for component in components:
        line = D(component["line_weight_lbs"])
        shippable_total += line
        if component["component_class"] in ("PRIMARY_FRAME_MEMBER", "SECONDARY_MEMBER"):
            frame_total += line
    return {
        "frame_weight_lbs": rhu(frame_total, 2),
        "shippable_weight_lbs": rhu(shippable_total, 2),
        "component_count": len(components),
    }


# --------------------------------------------------------------- price pipeline
def quote_price_pipeline(
    variant,
    config,
    builder,
    jurisdiction,
    kits,
    freight_distance_miles,
    adjustment_cents,
    billable_frame_weight_lbs,
):
    """PRD 3.4 -- the seven steps run in exactly this order and no other."""
    # 1. billable frame weight, supplied per variant by the caller.
    frame_weight = D(billable_frame_weight_lbs)

    # 2. component costs
    steel_cost_cents = money(frame_weight * C.STEEL_RATE_CENTS_PER_LB)
    panel_cost_cents = money(
        D(config["panel_area_sqft"]) * C.PANEL_RATE_CENTS_PER_SQFT[config["panel_profile"]]
    )
    accessory_cost_cents = 0
    accessory_weight = D(0)
    for kit in kits:
        accessory_cost_cents += int(kit["extended_price_cents"])
        accessory_weight += D(kit["extended_weight_lbs"])
    subtotal_cents = steel_cost_cents + panel_cost_cents + accessory_cost_cents

    # 3. freight, from weight not from money
    billable_weight_lbs = rhu(frame_weight + accessory_weight, 2)
    billable_tons = rhu(billable_weight_lbs / D(2000), 3)
    freight_cost_cents = money(
        billable_tons
        * C.FREIGHT_RATE_CENTS_PER_TON_MILE[jurisdiction["freight_zone"]]
        * D(freight_distance_miles)
    )

    # 4. discount base -- already contains the adjustment and freight
    pre_discount_total_cents = subtotal_cents + int(adjustment_cents) + freight_cost_cents

    # 5. rates
    tier_discount_rate = C.TIER_DISCOUNT_RATE[builder["tier"]]
    if pre_discount_total_cents >= C.VOLUME_TIER_3_CENTS:
        volume_discount_rate = C.VOLUME_TIER_3_RATE
    elif pre_discount_total_cents >= C.VOLUME_TIER_2_CENTS:
        volume_discount_rate = C.VOLUME_TIER_2_RATE
    elif pre_discount_total_cents >= C.VOLUME_TIER_1_CENTS:
        volume_discount_rate = C.VOLUME_TIER_1_RATE
    else:
        volume_discount_rate = D("0.00")
    total_discount_rate = min(C.MAX_DISCOUNT_RATE, tier_discount_rate + volume_discount_rate)

    # 6. price
    price_cents = money(D(pre_discount_total_cents) * (D(1) - total_discount_rate))

    return {
        "quote_variant": variant,
        "billable_frame_weight_lbs": rhu(frame_weight, 2),
        "steel_cost_cents": steel_cost_cents,
        "panel_cost_cents": panel_cost_cents,
        "accessory_cost_cents": accessory_cost_cents,
        "subtotal_cents": subtotal_cents,
        "billable_weight_lbs": billable_weight_lbs,
        "billable_tons": billable_tons,
        "freight_cost_cents": freight_cost_cents,
        "pre_discount_total_cents": pre_discount_total_cents,
        "tier_discount_rate": tier_discount_rate,
        "volume_discount_rate": volume_discount_rate,
        "total_discount_rate": total_discount_rate,
        "price_cents": price_cents,
    }


def adjustment_floor_cents(subtotal_cents):
    """PRD 3.4 -- twenty hundredths of subtotal_cents rounded half up, negated."""
    return -money(C.MAX_ADJUSTMENT_FRACTION * D(subtotal_cents))


def total_shippable_weight(design_shippable_weight_lbs, kits):
    total = D(design_shippable_weight_lbs)
    for kit in kits:
        total += D(kit["extended_weight_lbs"])
    return rhu(total, 2)


def shipment_load_gross_weight(resolved_components):
    total = D(0)
    for component in resolved_components:
        total += D(component["line_weight_lbs"])
    return rhu(total, 2)
