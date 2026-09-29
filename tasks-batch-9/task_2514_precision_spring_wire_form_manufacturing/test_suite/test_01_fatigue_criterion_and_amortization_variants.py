"""
The two dual-variant rules of the spring house: which fatigue line binds a wire
form, and which of the two tooling-recovery policies a program's money runs on.

Both rules take one identical input set and fork on a single declared field. The
engineering fork is `CustomerProgram.application_class`, which decides whether
the design persists the Goodman ratio or the harsher Soderberg ratio and, through
the life-tier table, a different whole number of predicted cycles. The financial
fork is `CustomerProgram.amortization_method`, which decides whether a hypothetical
lot recovers a flat per-piece forecast rate or an accelerated share of the tool's
remaining balance. The computed reads expose both sides of each fork side by side,
so one geometry and one ledger discriminate the two variants exactly.
"""

from prd_bench_local_runner.testing import get_success_data

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    DESIGN_ENGINEER_HEADERS,
    ENGINEERING_MANAGER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
)

# The two programs of the fatigue fork differ in `application_class` and nothing
# else that the engineering stack reads: both accept a 1.000 fatigue margin and
# demand no salt-spray endurance at all.
_INDUSTRIAL_PROGRAM = dict(
    program_code="PGM-IND-1",
    customer_name="Bramble Industrial Supply",
    application_class=C.CLASS_INDUSTRIAL,
    ppap_level=1,
    committed_pieces=100_000,
    minimum_order_quantity=5_000,
    required_salt_spray_hours=0,
    biocompatibility_required=False,
    min_fatigue_margin=1.0,
    required_ppk=1.0,
    amortization_method=C.FORECAST_BASIS,
)

_SAFETY_PROGRAM = dict(
    _INDUSTRIAL_PROGRAM,
    program_code="PGM-SAFE-1",
    customer_name="Northwind Drivetrain",
    application_class=C.CLASS_AUTOMOTIVE_SAFETY,
    ppap_level=3,
)

# One music-wire grade, unpeened duty: tensile 1750 MPa, so the ultimate shear
# strength is 1172.5 MPa and the shear yield strength 787.5 MPa.
_MUSIC_WIRE = dict(
    spec_code="MS-MW-1",
    wire_material=C.WIRE_MUSIC,
    tensile_grade_mpa=1750,
    shear_modulus_gpa=79.3,
    elastic_modulus_gpa=203.0,
    density_kg_per_m3=7850,
    coating=C.COATING_NONE,
    salt_spray_hours=0,
    biocompatible=False,
    cost_per_kg_cents=620,
)

# One geometry, D3: 2.0 mm wire, 16.0 mm outer diameter, 48.0 mm free length,
# 10 active coils, 90 N / 30 N, unpeened.
_D3_GEOMETRY = dict(
    form_type=C.FORM_COMPRESSION,
    end_type=C.END_CLOSED_GROUND,
    wire_diameter_mm=2.0,
    outer_diameter_mm=16.0,
    free_length_mm=48.0,
    active_coils=10,
    max_working_load_n=90,
    min_working_load_n=30,
    cycle_seconds_per_piece=3.0,
    shot_peening_required=False,
)

# The stress state D3 shares between the two programs, and the two ratios the
# two candidate denominators produce from it.
_D3_SPRING_RATE = 5.780
_D3_STRESS_AMPLITUDE = 160.43
_D3_MEAN_STRESS = 320.86
_D3_ENDURANCE_LIMIT = 350.00
_D3_MARGIN_GOODMAN = 1.366
_D3_MARGIN_SODERBERG = 1.155


def _draft_d3(api: ApiClient, program_overrides: dict, part_number: str) -> dict:
    """One D3 under one program, on the shared music-wire grade."""
    program = X.open_program(api, PROGRAM_MANAGER_HEADERS, **program_overrides)
    material = X.register_material(api, DESIGN_ENGINEER_HEADERS, **_MUSIC_WIRE)
    return X.draft_design(
        api,
        program["id"],
        material["id"],
        DESIGN_ENGINEER_HEADERS,
        part_number=part_number,
        **_D3_GEOMETRY,
    )


def test_industrial_class_binds_the_goodman_line_and_the_ten_million_cycle_tier(api):
    """PRD §3.2: "Which one binds is decided by the owning program's
    `application_class`: the design's `fatigue_criterion` is set to `SODERBERG`
    when the class is `AUTOMOTIVE_SAFETY` or `MEDICAL_IMPLANT`, and to `GOODMAN`
    for `AUTOMOTIVE_NON_SAFETY`, `MEDICAL_DEVICE` or `INDUSTRIAL`."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator
    belonging to the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "The ultimate shear strength is the tensile grade multiplied by
    0.67, and the shear yield strength is the tensile grade multiplied by 0.45."
    PRD §3.2: "A ratio of at least 1.300 yields ten million cycles."

    Design: Difficulty/dual_variant_calc/fatigue_criterion_soderberg_versus_goodman_on_identical_wire_form
    """
    design = _draft_d3(api, _INDUSTRIAL_PROGRAM, "D3-IND")

    assert design["fatigue_criterion"] == C.CRITERION_GOODMAN, (
        "an INDUSTRIAL program selects the GOODMAN criterion, got "
        f"{design['fatigue_criterion']!r}"
    )
    assert design["fatigue_margin_ratio"] == _D3_MARGIN_GOODMAN, (
        "the Goodman denominator divides the unrounded mean stress by the "
        f"ultimate shear strength, giving {_D3_MARGIN_GOODMAN}, got "
        f"{design['fatigue_margin_ratio']}"
    )
    assert design["fatigue_margin_ratio"] == A.expected_fatigue_margin(
        C.CLASS_INDUSTRIAL, 2.0, 16.0, 90, 30, 1750, False
    ), "the persisted ratio must be the Goodman variant of this stress state"
    assert design["predicted_fatigue_life_cycles"] == 10_000_000, (
        "a ratio of at least 1.300 yields ten million cycles, got "
        f"{design['predicted_fatigue_life_cycles']}"
    )


def test_automotive_safety_class_binds_the_soderberg_line_and_the_five_million_cycle_tier(api):
    """PRD §3.2: "Which one binds is decided by the owning program's
    `application_class`: the design's `fatigue_criterion` is set to `SODERBERG`
    when the class is `AUTOMOTIVE_SAFETY` or `MEDICAL_IMPLANT`, and to `GOODMAN`
    for `AUTOMOTIVE_NON_SAFETY`, `MEDICAL_DEVICE` or `INDUSTRIAL`."
    PRD §3.2: "`fatigue_margin_ratio` is then one divided by the denominator
    belonging to the criterion in force, rounded half up to three decimal places."
    PRD §3.2: "Because the shear yield strength is the smaller allowable, the
    `SODERBERG` variant always yields a strictly smaller margin than the
    `GOODMAN` variant for identical geometry, loads and material — the
    safety-critical classes are held to the harsher line, and the less
    conservative `GOODMAN` line divides the mean stress by the larger ultimate
    shear strength."
    PRD §3.2: "Otherwise a ratio of at least 1.150 yields five million."

    Design: Difficulty/dual_variant_calc/fatigue_criterion_soderberg_versus_goodman_on_identical_wire_form
    """
    design = _draft_d3(api, _SAFETY_PROGRAM, "D3-SAFE")

    assert design["fatigue_criterion"] == C.CRITERION_SODERBERG, (
        "an AUTOMOTIVE_SAFETY program selects the SODERBERG criterion, got "
        f"{design['fatigue_criterion']!r}"
    )
    assert design["fatigue_margin_ratio"] == _D3_MARGIN_SODERBERG, (
        "the Soderberg denominator divides the unrounded mean stress by the "
        f"smaller shear yield strength, giving {_D3_MARGIN_SODERBERG}, got "
        f"{design['fatigue_margin_ratio']}"
    )
    assert design["fatigue_margin_ratio"] == A.expected_fatigue_margin(
        C.CLASS_AUTOMOTIVE_SAFETY, 2.0, 16.0, 90, 30, 1750, False
    ), "the persisted ratio must be the Soderberg variant of this stress state"
    assert design["fatigue_margin_ratio"] < _D3_MARGIN_GOODMAN, (
        "the Soderberg margin is strictly smaller than the Goodman margin on "
        "identical geometry, loads and material"
    )
    assert design["predicted_fatigue_life_cycles"] == 5_000_000, (
        "a ratio that clears 1.150 but not 1.300 yields five million cycles, got "
        f"{design['predicted_fatigue_life_cycles']}"
    )


def _draft_both_d3(api: ApiClient):
    """The same D3 geometry and the same wire grade under both programs."""
    industrial = X.open_program(api, PROGRAM_MANAGER_HEADERS, **_INDUSTRIAL_PROGRAM)
    safety = X.open_program(api, PROGRAM_MANAGER_HEADERS, **_SAFETY_PROGRAM)
    material = X.register_material(api, DESIGN_ENGINEER_HEADERS, **_MUSIC_WIRE)
    d3_industrial = X.draft_design(
        api,
        industrial["id"],
        material["id"],
        DESIGN_ENGINEER_HEADERS,
        part_number="D3-IND",
        **_D3_GEOMETRY,
    )
    d3_safety = X.draft_design(
        api,
        safety["id"],
        material["id"],
        DESIGN_ENGINEER_HEADERS,
        part_number="D3-SAFE",
        **_D3_GEOMETRY,
    )
    return d3_industrial, d3_safety


def test_the_two_criteria_share_one_stress_state_from_the_identical_geometry(api):
    """PRD §3.2: "The value written to `spring_rate_n_per_mm` is that megapascal
    shear modulus multiplied by the wire diameter raised to the fourth power,
    divided by the product of eight, the mean coil diameter cubed, and the active
    coil count, with the result rounded half up to three decimal places."
    PRD §3.2: "Nothing outside the design's own geometry and the linked material's
    shear modulus contributes."
    PRD §3.2: "The amplitude and mean split is taken from the **unrounded** stress
    values, not from the two rounded fields: `stress_amplitude_mpa` is the
    unrounded maximum-load stress minus the unrounded minimum-load stress, divided
    by two, rounded half up to two decimal places once at the end; `mean_stress_mpa`
    is the sum of those same two unrounded stresses divided by two, rounded half up
    to two decimal places once at the end."

    Design: Difficulty/dual_variant_calc/fatigue_criterion_soderberg_versus_goodman_on_identical_wire_form
    """
    d3_industrial, d3_safety = _draft_both_d3(api)

    for label, design in (("industrial", d3_industrial), ("safety", d3_safety)):
        assert design["spring_rate_n_per_mm"] == _D3_SPRING_RATE, (
            f"the {label} copy of D3 must carry the geometry's own spring rate "
            f"{_D3_SPRING_RATE}, got {design['spring_rate_n_per_mm']}"
        )
        assert design["stress_amplitude_mpa"] == _D3_STRESS_AMPLITUDE, (
            f"the {label} copy of D3 must carry stress amplitude "
            f"{_D3_STRESS_AMPLITUDE}, got {design['stress_amplitude_mpa']}"
        )
        assert design["mean_stress_mpa"] == _D3_MEAN_STRESS, (
            f"the {label} copy of D3 must carry mean stress {_D3_MEAN_STRESS}, got "
            f"{design['mean_stress_mpa']}"
        )

    assert d3_industrial["spring_rate_n_per_mm"] == A.expected_spring_rate(
        79.3, 2.0, 16.0, 10
    ), "the shared spring rate is a pure function of geometry and shear modulus"
    assert (
        d3_industrial["fatigue_margin_ratio"] != d3_safety["fatigue_margin_ratio"]
    ), (
        "one identical stress state must still produce two different margins, "
        "because the two programs bind two different allowables"
    )
    assert (
        d3_industrial["predicted_fatigue_life_cycles"]
        != d3_safety["predicted_fatigue_life_cycles"]
    ), "the margin divergence propagates into two different life tiers"


def test_fatigue_analysis_read_exposes_both_lines_with_soderberg_in_force(api):
    """PRD §3.2: "A dedicated computed read exposes the fatigue picture without
    persisting anything."
    PRD §3.2: "It returns `criterion_in_force` — the `GOODMAN` or `SODERBERG`
    variant whose ratio the design actually persisted — alongside
    `fatigue_margin_goodman` and `fatigue_margin_soderberg`, each the three-decimal
    result of its own variant so the two lines can be compared side by side, the
    stress state they are built from as `stress_amplitude_mpa` and `mean_stress_mpa`
    at two decimal places, `endurance_limit_mpa` as the shear endurance limit after
    the shot-peening factor has been applied, rounded to two decimal places, and
    `predicted_fatigue_life_cycles` as the integer tier."
    PRD §3.2: "The endurance limit in shear is the tensile grade multiplied by 0.30
    when `shot_peening_required` is true and by 0.20 when it is false — shot peening
    buys half again as much fatigue strength, which is the whole reason the flag
    exists."

    Design: Difficulty/dual_variant_calc/fatigue_criterion_soderberg_versus_goodman_on_identical_wire_form
    """
    _, d3_safety = _draft_both_d3(api)

    analysis = get_success_data(
        api.get_fatigue_analysis(d3_safety["id"], DESIGN_ENGINEER_HEADERS)
    )

    assert analysis["criterion_in_force"] == C.CRITERION_SODERBERG, (
        "the read must name the variant the design persisted, got "
        f"{analysis['criterion_in_force']!r}"
    )
    assert analysis["fatigue_margin_goodman"] == _D3_MARGIN_GOODMAN, (
        f"the unused Goodman line is still reported as {_D3_MARGIN_GOODMAN}, got "
        f"{analysis['fatigue_margin_goodman']}"
    )
    assert analysis["fatigue_margin_soderberg"] == _D3_MARGIN_SODERBERG, (
        f"the binding Soderberg line is {_D3_MARGIN_SODERBERG}, got "
        f"{analysis['fatigue_margin_soderberg']}"
    )
    assert analysis["fatigue_margin_soderberg"] == d3_safety["fatigue_margin_ratio"], (
        "the variant in force must equal the ratio the design persisted"
    )
    assert analysis["endurance_limit_mpa"] == _D3_ENDURANCE_LIMIT, (
        "an unpeened design takes 0.20 of the tensile grade as its shear endurance "
        f"limit, so {_D3_ENDURANCE_LIMIT}, got {analysis['endurance_limit_mpa']}"
    )
    assert analysis["stress_amplitude_mpa"] == _D3_STRESS_AMPLITUDE
    assert analysis["mean_stress_mpa"] == _D3_MEAN_STRESS
    assert analysis["predicted_fatigue_life_cycles"] == 5_000_000, (
        "the read reports the same integer tier the design carries, got "
        f"{analysis['predicted_fatigue_life_cycles']}"
    )


# ── The financial fork: one ledger, two recovery policies ────────────────────
# An implant program that recovers tooling on the accelerated policy, committed to
# 40 000 pieces and with nothing shipped yet, so the whole commitment is open.
_MEDICAL_PROGRAM = dict(
    program_code="PGM-MED-1",
    customer_name="Halcyon Medical",
    application_class=C.CLASS_MEDICAL_IMPLANT,
    ppap_level=4,
    committed_pieces=40_000,
    minimum_order_quantity=2_000,
    required_salt_spray_hours=240,
    biocompatibility_required=True,
    min_fatigue_margin=1.35,
    required_ppk=1.67,
    amortization_method=C.ACTUAL_BASIS,
)

# D2: 1.2 mm wire, 10.0 mm outer diameter, 24.0 mm free length, 6 active coils,
# 25 N / 8 N, unpeened, on the passivated stainless grade.
_D2_GEOMETRY = dict(
    form_type=C.FORM_COMPRESSION,
    end_type=C.END_CLOSED_GROUND,
    wire_diameter_mm=1.2,
    outer_diameter_mm=10.0,
    free_length_mm=24.0,
    active_coils=6,
    max_working_load_n=25,
    min_working_load_n=8,
    cycle_seconds_per_piece=2.4,
    shot_peening_required=False,
)

_TOOL_COST_CENTS = 4_800_000
_HYPOTHETICAL_PIECES = 2_000
_FORECAST_RECOVERY_CENTS = 240_000
_ACTUAL_RECOVERY_CENTS = 360_000


def _medical_tooling_ledger(api: ApiClient):
    """One implant program, one 4 800 000-cent tool, one quote binding the two."""
    program = X.open_program(api, PROGRAM_MANAGER_HEADERS, **_MEDICAL_PROGRAM)
    material = X.register_biocompatible_material(api, DESIGN_ENGINEER_HEADERS)
    design = X.draft_design(
        api,
        program["id"],
        material["id"],
        DESIGN_ENGINEER_HEADERS,
        part_number="D2-MED",
        **_D2_GEOMETRY,
    )
    tool = X.capitalise_tooling(
        api,
        design["id"],
        ENGINEERING_MANAGER_HEADERS,
        tool_code="TL-D2",
        original_cost_cents=_TOOL_COST_CENTS,
    )
    X.price_program(
        api, program, design["id"], PROGRAM_MANAGER_HEADERS, quoted_qty=40_000
    )
    return program, design, tool


def _amortization_read(api: ApiClient, program_id: str, piece_count: int) -> dict:
    return get_success_data(
        api.get_tooling_amortization(
            program_id, PROGRAM_MANAGER_HEADERS, params={"piece_count": piece_count}
        )
    )


def test_forecast_variant_recovers_the_flat_per_piece_rate_off_the_committed_basis(api):
    """PRD §3.4: "Under `FORECAST_BASIS` — a straight-line forecast recovery — the
    amount is the lot's `piece_count` multiplied by the tool's frozen
    `amort_per_piece_cents`, capped at the tool's live `unamortized_cents`;
    whichever of the two is smaller is posted."
    PRD §3.4: "Recovery is linear in piece count and completely independent of how
    much of the tool remains outstanding."
    PRD §3.4: "When the tool's `amort_per_piece_cents` has not yet been frozen, the
    forecast figure is computed on the fly as `original_cost_cents` divided by the
    program's `committed_pieces`, rounded up to a whole cent, multiplied through as
    the forecast variant prescribes."

    Design: Difficulty/dual_variant_calc/tooling_amortization_forecast_versus_accelerated_on_identical_ledger
    """
    program, _, tool = _medical_tooling_ledger(api)

    read = _amortization_read(api, program["id"], _HYPOTHETICAL_PIECES)

    assert read["tooling_asset_id"] == tool["id"], (
        "the read must consult the newest tooling asset of the most recently "
        "quoted design"
    )
    assert read["forecast_basis_recovery_cents"] == _FORECAST_RECOVERY_CENTS, (
        "4 800 000 cents over 40 000 committed pieces rounds up to 120 cents a "
        f"piece, so 2 000 pieces forecast {_FORECAST_RECOVERY_CENTS}, got "
        f"{read['forecast_basis_recovery_cents']}"
    )
    assert read["forecast_basis_recovery_cents"] == A.expected_forecast_recovery_cents(
        _HYPOTHETICAL_PIECES,
        A.expected_amort_per_piece_cents(_TOOL_COST_CENTS, 40_000),
        _TOOL_COST_CENTS,
    ), "the straight-line figure is pieces times the rate, capped at the balance"
    assert read["amortization_method"] == C.ACTUAL_BASIS, (
        "the forecast figure is hypothetical: the program's own policy is still "
        f"ACTUAL_BASIS, got {read['amortization_method']!r}"
    )


def test_accelerated_variant_recovers_half_again_the_pro_rata_remaining_balance(api):
    """PRD §3.4: "Under `ACTUAL_BASIS` — an accelerated declining recovery — the
    amount starts from the tool's live `unamortized_cents` multiplied by an
    acceleration factor of 1.5, multiplied by the lot's `piece_count`, divided by
    the program's `open_commitment_pieces` (or by 1 if that figure is zero or
    lower, so the division is always defined), rounded **up** toward positive
    infinity to a whole cent, and then capped at the tool's live
    `unamortized_cents`; again the smaller of the two is posted."
    PRD §3.4: "This variant recovers one and a half times the pro-rata share of the
    *remaining* balance against the *remaining* commitment, front-loading recovery
    heavily in the early lots."
    PRD §3.4: "Both variants are integral cents; there is no half-up rounding
    anywhere in this rule."

    Design: Difficulty/dual_variant_calc/tooling_amortization_forecast_versus_accelerated_on_identical_ledger
    """
    program, _, _ = _medical_tooling_ledger(api)

    read = _amortization_read(api, program["id"], _HYPOTHETICAL_PIECES)

    assert read["actual_basis_recovery_cents"] == _ACTUAL_RECOVERY_CENTS, (
        "1.5 times 4 800 000 times 2 000 over 40 000 open pieces is "
        f"{_ACTUAL_RECOVERY_CENTS} cents, got {read['actual_basis_recovery_cents']}"
    )
    assert read["actual_basis_recovery_cents"] == A.expected_actual_recovery_cents(
        _TOOL_COST_CENTS, _HYPOTHETICAL_PIECES, 40_000
    ), "the accelerated figure scales the remaining balance, not the original cost"
    assert float(read["actual_basis_recovery_cents"]).is_integer(), (
        "both variants are integral cents, got "
        f"{read['actual_basis_recovery_cents']}"
    )
    assert (
        read["actual_basis_recovery_cents"] - read["forecast_basis_recovery_cents"]
        == 120_000
    ), (
        "the same 2 000-piece draw against the same ledger differs by 120 000 cents "
        "between the two policies"
    )
    assert (
        read["actual_basis_recovery_cents"] > read["forecast_basis_recovery_cents"]
    ), "the accelerated policy front-loads recovery ahead of the straight line"


def test_the_side_by_side_read_leaves_the_live_ledger_and_the_commitment_untouched(api):
    """PRD §3.4: "A newly capitalised tool opens in `amortization_status` `PENDING`
    with `recovered_cents` at 0 and `unamortized_cents` equal to
    `original_cost_cents`."
    PRD §3.4: "Both `amortization_basis_pieces` and `amort_per_piece_cents` stay
    null: until the customer has granted full approval, nobody knows over how many
    pieces the tool will be recovered."
    PRD §3.4: "A computed read on the program exposes them side by side for a
    hypothetical lot of a stated `piece_count`, returning the program's own
    `amortization_method`, the `tooling_asset_id` of the newest tooling asset by
    `created_at` for the program's most recently quoted design, that tool's
    `original_cost_cents`, `recovered_cents` and `unamortized_cents`, the program's
    live `open_commitment_pieces`, and then both hypothetical figures:
    `forecast_basis_recovery_cents` and `actual_basis_recovery_cents`."

    Design: Difficulty/dual_variant_calc/tooling_amortization_forecast_versus_accelerated_on_identical_ledger
    """
    program, _, tool = _medical_tooling_ledger(api)

    read = _amortization_read(api, program["id"], _HYPOTHETICAL_PIECES)

    assert read["original_cost_cents"] == _TOOL_COST_CENTS
    assert read["recovered_cents"] == 0, (
        "nothing has shipped, so the tool has recovered nothing, got "
        f"{read['recovered_cents']}"
    )
    assert read["unamortized_cents"] == _TOOL_COST_CENTS, (
        "the whole capitalised cost is still outstanding, got "
        f"{read['unamortized_cents']}"
    )
    assert read["open_commitment_pieces"] == 40_000, (
        "no lot has been allocated, so the whole commitment is still open, got "
        f"{read['open_commitment_pieces']}"
    )

    after = get_success_data(
        api.get_tooling_asset(tool["id"], ENGINEERING_MANAGER_HEADERS)
    )
    assert after["recovered_cents"] == 0, (
        "a computed read posts nothing to the ledger, got "
        f"{after['recovered_cents']}"
    )
    assert after["unamortized_cents"] == _TOOL_COST_CENTS, (
        "the tool's outstanding balance must be unchanged by the read"
    )
    assert after["amortization_status"] == C.AMORT_PENDING, (
        "the tool is still PENDING, got " f"{after['amortization_status']!r}"
    )
    assert after["amort_per_piece_cents"] is None, (
        "the per-piece rate is frozen only at PRODUCTION_RELEASED, got "
        f"{after['amort_per_piece_cents']}"
    )
    assert after["amortization_basis_pieces"] is None, (
        "the amortization basis is frozen only at PRODUCTION_RELEASED, got "
        f"{after['amortization_basis_pieces']}"
    )
    A.assert_tooling_ledger_conserved(after)
