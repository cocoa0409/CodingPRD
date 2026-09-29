"""Arithmetic that runs in two variants over one set of inputs.

Two computations in this API are variant-parameterised: the load combination
family chosen when a design is opened, and the pricing variant that bills steel
on a parametric estimate at quoting time and on the detailed bill of material at
release time.  Both variants read the same configuration, so the only way to
tell them apart is the number each produces.
"""

from test_helpers import (
    STANDARD_KITS,
    assert_credit_ledger_conserved,
    assert_order_dimensions,
    assert_rate,
    assert_weight,
    chain_locked_configuration,
    chain_sealed_order,
    create_design,
    full_bom,
    get_builder,
    get_configuration,
    get_design,
    get_order,
    release_order,
)


def test_01_lock_derives_the_three_pressures_a_load_combination_consumes():
    """Locking pins the dead, wind and snow pressures the combinations read.

    PRD §3.6: "Three pressures from the configuration feed it: the dead load
    ``dead_load_psf``, the wind pressure ``design_wind_pressure_psf``, and the
    roof snow load ``roof_snow_load_psf``."

    PRD §3.3: "``dead_load_psf`` is the panel dead load for the chosen
    ``panel_profile`` — 1.20 pounds per square foot for ``PBR``, 1.60 for
    ``STANDING_SEAM``, 1.10 for ``R_PANEL`` — plus a flat frame allowance of
    1.50 pounds per square foot, plus two hundredths of a pound per square foot
    for each unit of ``insulation_r_value``, with the total rounded half up to
    two decimal places."

    PRD §3.3: "``design_wind_pressure_psf`` is the velocity pressure multiplied
    by the governing pressure coefficient multiplied by the height factor,
    rounded half up to two decimal places."

    PRD §3.3: "``roof_snow_load_psf`` is the jurisdiction's
    ``ground_snow_load_psf`` multiplied by a roof factor of 0.70, rounded half
    up to two decimal places."

    Design: Difficulty/dual_variant_calc/asd_vs_lrfd_governing_combination_on_engineering_design
    """
    chain = chain_locked_configuration()
    configuration = chain["configuration"]

    # PBR 1.20 + frame allowance 1.50 + 0.02 x R-19.
    assert configuration["dead_load_psf"] == 3.08
    # Exposure C 0.85, 140 mph, low-slope roof coefficient 1.10, height factor 1.04.
    assert configuration["design_wind_pressure_psf"] == 48.79
    # Ground snow 5 psf x 0.70.
    assert configuration["roof_snow_load_psf"] == 3.50


def test_02_asd_design_governs_on_the_wind_combination_factored_to_six_tenths():
    """An ASD design evaluates only the three ASD candidates.

    PRD §3.6: "Under the ``ASD`` variant three candidate combinations are
    evaluated, each rounded half up to two decimal places, in this list order:
    ``ASD_D_PLUS_S``, the dead load plus the snow load; ``ASD_D_PLUS_0_6W``, the
    dead load plus six tenths of the wind pressure; and
    ``ASD_D_PLUS_0_75S_PLUS_0_45W``, the dead load plus three quarters of the
    snow load plus forty-five hundredths of the wind pressure."

    PRD §3.6: "``governing_load_psf`` is the largest of the three rounded
    candidate pressures, and ``governing_combination`` is the name of the
    candidate that produced it."

    PRD §3.6: "From the governing pressure the system derives
    ``tributary_load_kip_per_ft`` as ``governing_load_psf`` multiplied by the
    configuration's ``bay_spacing_ft`` divided by 1000, rounded half up to six
    decimal places, and then ``required_moment_kip_ft`` as
    ``tributary_load_kip_per_ft`` multiplied by the square of the
    configuration's ``clear_span_ft`` divided by 8, rounded half up to two
    decimal places."

    Design: Difficulty/dual_variant_calc/asd_vs_lrfd_governing_combination_on_engineering_design
    """
    chain = chain_locked_configuration()
    configuration = chain["configuration"]

    design = create_design(
        configuration["id"], configuration["version"], design_variant="ASD"
    )

    # 3.08 + 0.6 x 48.79 = 32.354 -> 32.35, beating 6.58 and 27.66.
    assert design["governing_combination"] == "ASD_D_PLUS_0_6W"
    assert design["governing_load_psf"] == 32.35
    # 32.35 x 25 / 1000, then x 100^2 / 8.
    assert design["tributary_load_kip_per_ft"] == 0.808750
    assert design["required_moment_kip_ft"] == 1010.94


def test_03_lrfd_design_on_the_same_configuration_governs_far_higher():
    """The LRFD candidate list takes wind at full value, so the moment jumps.

    PRD §3.6: "Under the ``LRFD`` variant three different candidates are
    evaluated, each likewise rounded half up to two decimal places, in this list
    order: ``LRFD_1_4D``, one and four tenths of the dead load;
    ``LRFD_1_2D_PLUS_1_6S``, one and two tenths of the dead load plus one and
    six tenths of the snow load; and ``LRFD_1_2D_PLUS_1_0W_PLUS_0_5S``, one and
    two tenths of the dead load plus the full wind pressure plus half the snow
    load."

    PRD §3.6: "Only the chosen variant's list is considered — an ``ASD`` design
    never evaluates an ``LRFD`` candidate and vice versa."

    PRD §3.6: "Because ``LRFD`` factors wind at its full value and dead at 1.2
    while ``ASD`` factors wind down to 0.6, the wind-dominated combination
    governs far higher under ``LRFD``, and for identical configuration loads an
    ``LRFD`` design will show a materially larger required moment than an
    ``ASD`` design."

    PRD §3.6: "First, every earlier design of the same ``configuration_id``
    whose ``status`` is ``DRAFT``, ``SUBMITTED``, ``APPROVED`` or
    ``REVISION_REQUIRED`` is transitioned to ``SUPERSEDED``"

    Design: Difficulty/dual_variant_calc/asd_vs_lrfd_governing_combination_on_engineering_design
    """
    chain = chain_locked_configuration()
    configuration = chain["configuration"]

    asd_design = create_design(
        configuration["id"], configuration["version"], design_variant="ASD"
    )
    # Opening a design increments the configuration's version, so the second
    # create must pin the version it left behind.
    reread = get_configuration(configuration["id"])
    lrfd_design = create_design(
        reread["id"], reread["version"], design_variant="LRFD"
    )

    # 1.2 x 3.08 + 48.79 + 0.5 x 3.50 = 54.236 -> 54.24, beating 4.31 and 9.30.
    assert lrfd_design["governing_combination"] == "LRFD_1_2D_PLUS_1_0W_PLUS_0_5S"
    assert lrfd_design["governing_load_psf"] == 54.24
    assert lrfd_design["tributary_load_kip_per_ft"] == 1.356000
    assert lrfd_design["required_moment_kip_ft"] == 1695.00
    # The ASD design is materially lower and has been superseded.
    assert lrfd_design["required_moment_kip_ft"] > asd_design["required_moment_kip_ft"]
    assert get_design(asd_design["id"])["status"] == "SUPERSEDED"


def test_04_preliminary_quote_bills_steel_on_the_parametric_frame_estimate():
    """The PRELIMINARY variant reads the configuration's estimated frame weight.

    PRD §3.4: "Under the ``PRELIMINARY`` variant,
    ``billable_frame_weight_lbs`` is the configuration's
    ``estimated_frame_weight_lbs``."

    PRD §3.4: "``steel_cost_cents`` is ``billable_frame_weight_lbs`` multiplied
    by a steel rate of 92 cents per pound, rounded half up to whole cents."

    PRD §3.4: "``billable_weight_lbs`` is ``billable_frame_weight_lbs`` plus the
    sum of ``extended_weight_lbs`` over every accessory kit of the
    configuration, rounded half up to two decimal places."

    PRD §3.4: "``freight_cost_cents`` is ``billable_tons`` multiplied by the
    rate for the jurisdiction's ``freight_zone`` multiplied by the quote's
    ``freight_distance_miles``, rounded half up to whole cents."

    PRD §3.4: "The price in cents is ``pre_discount_total_cents`` multiplied by
    one minus ``total_discount_rate``, rounded half up to whole cents."

    Design: Difficulty/dual_variant_calc/preliminary_vs_final_price_variant_on_order_release
    """
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    quote = chain["quote"]

    assert quote["quote_variant"] == "PRELIMINARY"
    # 10000 sqft x 4.6 x span factor 1.08.
    assert_weight(quote["billable_frame_weight_lbs"], 49680.00)
    assert quote["steel_cost_cents"] == 4570560
    assert quote["panel_cost_cents"] == 4123350
    assert quote["accessory_cost_cents"] == 1159949
    assert quote["subtotal_cents"] == 9853859
    # 49680.00 + 1281.00 + 264.75 pounds, then divided by 2000.
    assert_weight(quote["billable_weight_lbs"], 51225.75)
    assert quote["billable_tons"] == 25.613
    assert quote["freight_cost_cents"] == 165972
    assert quote["pre_discount_total_cents"] == 10019831
    assert_rate(quote["tier_discount_rate"], 0.03)
    assert_rate(quote["volume_discount_rate"], 0.00)
    assert quote["quoted_price_cents"] == 9719236


def test_05_release_reprices_under_the_final_variant_on_the_design_weight():
    """The FINAL variant substitutes the approved design's frame weight.

    PRD §3.4: "Under the ``FINAL`` variant, ``billable_frame_weight_lbs`` is
    instead the ``frame_weight_lbs`` of the engineering design at the order's
    ``engineering_design_id``, a design that must be ``APPROVED``."

    PRD §3.4: "This is the only input that differs between the variants, and
    because it flows into steel cost, billable tonnage and freight together, a
    single substitution moves three numbers at once."

    PRD §3.4: "*Step seven* runs under the ``FINAL`` variant only:
    ``price_delta_cents`` is the order's ``final_price_cents`` minus the
    originating quote's ``quoted_price_cents``."

    PRD §3.4: "The delta is signed, and a detailed design that came in lighter
    than the parametric estimate produces a negative delta."

    Design: Difficulty/dual_variant_calc/preliminary_vs_final_price_variant_on_order_release
    """
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    design = get_design(chain["design"]["id"])
    # The detailed bill weighs less than the parametric estimate of 49680.00.
    assert_weight(design["frame_weight_lbs"], 46854.48)

    order = release_order(chain["order"]["id"], chain["order"]["version"])

    assert order["final_price_cents"] == 9458205
    assert order["price_delta_cents"] == -261031
    assert order["final_price_cents"] < chain["quote"]["quoted_price_cents"]
    assert_order_dimensions(order, "ENG_SEALED", "PROD_RELEASED")


def test_06_the_signed_delta_is_what_moves_the_builder_credit_ledger():
    """Release moves committed credit by the delta, not by the whole price.

    PRD §2.9: "Three operations move the ledger: accepting a quote increases
    ``credit_used_cents`` by the quote's ``quoted_price_cents``; releasing an
    order to fabrication moves ``credit_used_cents`` by the order's
    ``price_delta_cents`` (which may be negative, in which case used credit
    falls); cancelling that release moves ``credit_used_cents`` by the negation
    of ``price_delta_cents``, restoring exactly the value the ledger held
    immediately after acceptance."

    PRD §2.9: "A builder's ``credit_limit_cents`` is set at onboarding;
    ``credit_used_cents`` starts at 0 and ``credit_available_cents`` is always
    exactly ``credit_limit_cents`` minus ``credit_used_cents``."

    Design: Difficulty/dual_variant_calc/preliminary_vs_final_price_variant_on_order_release
    """
    chain = chain_sealed_order(kits=STANDARD_KITS, components=full_bom())
    builder_id = chain["builder"]["id"]

    after_accept = get_builder(builder_id)
    assert after_accept["credit_used_cents"] == 9719236
    assert_credit_ledger_conserved(after_accept)

    release_order(chain["order"]["id"], chain["order"]["version"])

    after_release = get_builder(builder_id)
    # 9719236 + (-261031).
    assert after_release["credit_used_cents"] == 9458205
    assert after_release["credit_available_cents"] == 190541795
    assert_credit_ledger_conserved(after_release)
    assert get_order(chain["order"]["id"])["price_delta_cents"] == -261031
