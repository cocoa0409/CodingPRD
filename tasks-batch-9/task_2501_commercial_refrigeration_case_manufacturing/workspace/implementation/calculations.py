"""Every calculation of PRD section 3, with the pinned rounding order.

All rounding is round-half-up (PRD 2.6).  Money is always an integer count of
cents; nothing here ever uses binary floating point arithmetic.
"""

from decimal import Decimal, ROUND_HALF_UP

ZERO = Decimal(0)


def D(value):
    if isinstance(value, Decimal):
        return value
    if isinstance(value, int):
        return Decimal(value)
    return Decimal(str(value))


def rhu(value, places):
    quantum = Decimal(1).scaleb(-places)
    return D(value).quantize(quantum, rounding=ROUND_HALF_UP)


def rhu_cents(value):
    return int(rhu(value, 0))


def dmax(a, b):
    a = D(a)
    b = D(b)
    return a if a > b else b


# --------------------------------------------------------------------------
# airflow_load_model  (PRD 3.2)
# --------------------------------------------------------------------------
K_INF = {"HT": D("0.62"), "MT": D("0.78"), "LT": D("1.05")}
CURTAIN_REDUCTION_PER_LAYER = D("0.12")
MIN_CURTAIN_FACTOR = D("0.55")
VELOCITY_REF_MPS = D("0.45")
VELOCITY_SENSITIVITY = D("0.20")
ANTI_SWEAT_W_PER_DOOR = {"HT": D(0), "MT": D(18), "LT": D(42)}
SELF_CONTAINED_REJECT_FRACTION = D("0.08")
DEFROST_W_PER_CYCLE_PER_SQFT = D("3.5")

LINE_SET_CHARGE_GRAMS_PER_FT = 26


def airflow_load_model(model):
    spread = dmax(ZERO, D(model["ambient_dew_point_c"]) - D(model["case_air_temp_c"]))

    curtain_factor = dmax(
        MIN_CURTAIN_FACTOR,
        D(1) - CURTAIN_REDUCTION_PER_LAYER * D(model["curtain_layers"] - 1),
    )
    excess = dmax(ZERO, D(model["discharge_velocity_mps"]) - VELOCITY_REF_MPS)
    velocity_factor = D(1) + VELOCITY_SENSITIVITY * excess / VELOCITY_REF_MPS

    tda = D(model["tda_sqft"])
    infiltration = rhu(
        K_INF[model["temperature_class"]] * tda * spread * curtain_factor * velocity_factor,
        2,
    )
    lighting = rhu(D(model["lighting_w_per_ft"]) * D(model["nominal_length_ft"]), 2)
    fan = rhu(D(model["fan_w_per_ft"]) * D(model["nominal_length_ft"]), 2)
    defrost = rhu(
        DEFROST_W_PER_CYCLE_PER_SQFT * D(model["defrost_cycles_per_day"]) * tda / D(24),
        2,
    )
    anti_sweat = rhu(
        ANTI_SWEAT_W_PER_DOOR[model["temperature_class"]] * D(model["glass_door_count"]),
        2,
    )

    subtotal = infiltration + lighting + fan + defrost + anti_sweat
    if model["system_type"] == "SELF_CONTAINED":
        reject = rhu(SELF_CONTAINED_REJECT_FRACTION * subtotal, 2)
    else:
        reject = rhu(ZERO, 2)
    total = rhu(subtotal + reject, 2)

    model["curtain_factor"] = curtain_factor
    model["velocity_factor"] = velocity_factor
    model["infiltration_load_w"] = infiltration
    model["lighting_load_w"] = lighting
    model["fan_load_w"] = fan
    model["defrost_load_w"] = defrost
    model["anti_sweat_load_w"] = anti_sweat
    model["total_design_load_w"] = total


def installed_charge_of(model):
    """The installed charge basis: nameplate charge plus the line-set charge."""
    return model["charge_grams"] + LINE_SET_CHARGE_GRAMS_PER_FT * model["line_set_length_ft"]


def refrigerant_charge_basis(model, refrigerant):
    installed = installed_charge_of(model)
    gwp = D(refrigerant["gwp_100yr"])
    model["installed_charge_grams"] = installed
    model["nameplate_co2e_kg"] = rhu(D(model["charge_grams"]) / D(1000) * gwp, 1)
    model["installed_co2e_kg"] = rhu(D(installed) / D(1000) * gwp, 1)


# --------------------------------------------------------------------------
# energy_limit_daily_kwh / energy_use_index  (PRD 3.3)
# --------------------------------------------------------------------------
AMBIENT_SENSITIVITY_PER_C = D("0.035")
DEFROST_KWH_PER_CYCLE = D("0.28")


def energy_limit_daily_kwh(standard, tda_sqft):
    return rhu(D(standard["limit_coefficient_a"]) * D(tda_sqft)
               + D(standard["limit_constant_b"]), 3)


def energy_use_index(test):
    measured = D(test["measured_kwh_24h"])
    pinned_tda = D(test["pinned_tda_sqft"])
    limit = D(test["limit_daily_kwh"])

    lab_index = rhu(measured / pinned_tda, 3)

    uplift = D(1) + AMBIENT_SENSITIVITY_PER_C * dmax(
        ZERO, D(test["store_ambient_c"]) - D(test["test_ambient_c"])
    )
    missed = dmax(
        ZERO,
        D(test["pinned_defrost_cycles_per_day"]) - D(test["measured_defrost_cycles"]),
    )
    field_daily = rhu(measured * uplift + DEFROST_KWH_PER_CYCLE * missed, 3)
    field_index = rhu(field_daily / pinned_tda, 3)

    test["lab_rated_index"] = lab_index
    test["field_projected_daily_kwh"] = field_daily
    test["field_projected_index"] = field_index
    test["field_exceedance"] = bool(measured <= limit and field_daily > limit)


# --------------------------------------------------------------------------
# case_unit_price_cents / store_plan_commercial_total  (PRD 3.6)
# --------------------------------------------------------------------------
BASE_PRICE_PER_FT_CENTS = {"HT": D(78000), "MT": D(96000), "LT": D(124000)}
LENGTH_TIER = {4: D("1.15"), 6: D("1.06"), 8: D("1.00"), 12: D("0.94")}
OPTION_ADDER_CENTS = {
    "LED_CANOPY": 42000,
    "NIGHT_CURTAIN": 28500,
    "GLASS_DOOR_UPGRADE": 165000,
    "SHELF_LIGHTING": 51500,
    "DIGITAL_PRICE_RAIL": 73500,
}
END_CAP_ADDER_CENTS_PER_SIDE = 87000
END_CAP_SIDES = {"NONE": 0, "LEFT": 1, "RIGHT": 1, "BOTH": 2}
SYSTEM_ADDER_CENTS = {"REMOTE": 118000, "SELF_CONTAINED": 320000}

FREIGHT_PER_LINEAR_FT_CENTS = D(9500)
FREIGHT_CAP_FRACTION = D("0.04")
INSTALL_ALLOWANCE_FRACTION = D("0.025")


def case_unit_price_cents(line, model):
    length = line["length_ft"]
    base_cents = rhu_cents(
        BASE_PRICE_PER_FT_CENTS[model["temperature_class"]] * D(length) * LENGTH_TIER[length]
    )
    option_cents = sum(OPTION_ADDER_CENTS[o] for o in line["merchandising_options"])
    endcap_cents = END_CAP_ADDER_CENTS_PER_SIDE * END_CAP_SIDES[line["end_cap"]]
    system_cents = SYSTEM_ADDER_CENTS[model["system_type"]]

    unit_price = base_cents + option_cents + endcap_cents + system_cents
    line["unit_price_cents"] = unit_price
    line["extended_price_cents"] = unit_price * line["quantity"]


def volume_discount_bps(subtotal_cents):
    if subtotal_cents < 5000000:
        return 0
    if subtotal_cents < 10000000:
        return 300
    if subtotal_cents < 20000000:
        return 550
    return 800


def store_plan_commercial_total(plan, lines):
    # step 1
    subtotal = 0
    total_linear_feet = 0
    for line in lines:
        subtotal += line["extended_price_cents"]
        total_linear_feet += line["length_ft"] * line["quantity"]
    # step 2
    bps = volume_discount_bps(subtotal)
    # step 3
    discount = rhu_cents(D(subtotal) * D(bps) / D(10000))
    # step 4
    net = subtotal - discount
    # step 5
    tariff = rhu_cents(FREIGHT_PER_LINEAR_FT_CENTS * D(total_linear_feet))
    cap = rhu_cents(D(net) * FREIGHT_CAP_FRACTION)
    freight = tariff if tariff < cap else cap
    # step 6
    allowance = rhu_cents(D(net) * INSTALL_ALLOWANCE_FRACTION)

    plan["subtotal_cents"] = subtotal
    plan["volume_discount_bps"] = bps
    plan["volume_discount_cents"] = discount
    plan["net_cents"] = net
    plan["freight_cents"] = freight
    plan["install_allowance_cents"] = allowance
    plan["total_cents"] = net + freight + allowance


# --------------------------------------------------------------------------
# warranty_reserve_balance  (PRD 3.7 / 3.9)
# --------------------------------------------------------------------------
WARRANTY_ACCRUAL_BPS = D(275)
OPEN_CLAIM_FACTOR = D("0.60")


def warranty_accrual_cents(work_orders):
    total = 0
    for wo in work_orders:
        if wo["status"] == "SCRAPPED":
            continue
        total += rhu_cents(D(wo["unit_price_cents"]) * WARRANTY_ACCRUAL_BPS / D(10000))
    return total


def warranty_incurred_cents(claims):
    total = 0
    for claim in claims:
        status = claim["status"]
        if status == "RESOLVED":
            total += claim["total_cost_cents"] or 0
        elif status in ("OPEN", "PARTS_RESERVED"):
            total += rhu_cents(D(claim["estimated_cost_cents"]) * OPEN_CLAIM_FACTOR)
    return total


# --------------------------------------------------------------------------
# warranty_coverage_window  (PRD 3.9)
# --------------------------------------------------------------------------
WARRANTY_TERM_MONTHS = {
    "COMPRESSOR_FAILURE": 60,
    "DOOR_GASKET": 12,
    "CONTROLLER": 12,
    "GLASS_FOG": 12,
}
