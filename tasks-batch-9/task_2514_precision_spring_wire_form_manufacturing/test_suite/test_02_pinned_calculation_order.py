"""
Two calculations whose *order* is the rule, not just their arithmetic.

The wire reservation is rounding-order sensitive: the per-piece mass is rounded
to exactly six decimals and stored on the design before anything scales it, so a
ten-thousand-piece run reserves 218.206 kg, while carrying an unrounded mass
through the scale-and-inflate and rounding once at the end lands on 218.205 kg.
The program quote is evaluation-order sensitive in a different way: the volume
tier is read off the pre-discount subtotal while the tooling-amortization cap is
read off the post-discount unit cost, so a quantity sitting just under the first
breakpoint prices at 186152 cents, whereas keying the tier on the amortized unit
price would cross the breakpoint and land on 186178.
"""

from test_helpers import assertions as A
from test_helpers import constants as C
from test_helpers import fixtures as X
from test_helpers.api_client import ApiClient
from test_helpers.test_users import (
    ENGINEERING_MANAGER_HEADERS,
    PROGRAM_MANAGER_HEADERS,
)

# The safety program the reservation scenario runs under.
_SAFETY_PROGRAM = dict(
    program_code="PGM-AUTO-1",
    customer_name="Northwind Drivetrain",
    application_class=C.CLASS_AUTOMOTIVE_SAFETY,
    ppap_level=3,
    committed_pieces=500_000,
    minimum_order_quantity=25_000,
    required_salt_spray_hours=96,
    biocompatibility_required=False,
    min_fatigue_margin=1.2,
    required_ppk=1.33,
    amortization_method=C.FORECAST_BASIS,
)

# A 500.000 kg heat, so the reservation's residue is a distinctive number.
_HEAT = dict(heat_number="HT-500", received_kg=500.0)

_PLANNED_PIECES = 10_000
_RESERVED_KG = 218.206
_FORBIDDEN_RESERVED_KG = 218.205
_ON_HAND_AFTER_KG = 281.794


def _run_on_certified_heat(api: ApiClient):
    """The canonical D1 world, then one run of 10 000 pieces off the 500 kg heat."""
    world = X.build_world(
        api, "certified_wire", program=_SAFETY_PROGRAM, wire_lot=_HEAT
    )
    run = X.open_run(
        api,
        world.setup_id,
        world.wire_lot_id,
        world.design_id,
        planned_pieces=_PLANNED_PIECES,
    )
    return world, run


def test_reservation_scales_the_stored_six_decimal_mass_and_rounds_once_at_the_end(api):
    """PRD §3.7: "The kilograms a run reserves are computed in a pinned order that
    must not be rearranged."
    PRD §3.7: "Start from the design's **stored** `wire_mass_per_piece_kg`, already
    rounded to six decimal places."
    PRD §3.7: "Round the result half up to three decimal places, once, at the very
    end."
    PRD §3.7: "Recomputing an unrounded per-piece mass and scaling that instead
    changes the third decimal on large runs and is wrong."
    PRD §3.2: "This stored six-decimal value is the **only** per-piece mass any
    downstream rule may read; recomputing an unrounded mass for a reservation or a
    consumption posting produces different kilograms and is wrong."

    Design: Difficulty/combinatorial_formula/wire_reservation_pinned_rounding_order_mode_b
    """
    world, run = _run_on_certified_heat(api)

    assert world.design["wire_mass_per_piece_kg"] == C.D1_WIRE_MASS_PER_PIECE_KG, (
        "the design must carry the six-decimal per-piece mass "
        f"{C.D1_WIRE_MASS_PER_PIECE_KG}, got "
        f"{world.design['wire_mass_per_piece_kg']}"
    )
    A.assert_decimal_places(
        world.design["wire_mass_per_piece_kg"], 6, "wire_mass_per_piece_kg"
    )
    assert run["wire_reserved_kg"] == _RESERVED_KG, (
        "0.021185 kg times 10 000 pieces inflated three percent and rounded once "
        f"is {_RESERVED_KG} kg, got {run['wire_reserved_kg']}"
    )
    assert run["wire_reserved_kg"] != _FORBIDDEN_RESERVED_KG, (
        "carrying an unrounded per-piece mass through the scale-and-inflate would "
        f"land on {_FORBIDDEN_RESERVED_KG} kg, which is the forbidden order"
    )
    assert run["wire_reserved_kg"] == A.expected_wire_reserved_kg(
        C.D1_WIRE_MASS_PER_PIECE_KG, _PLANNED_PIECES
    ), "the reservation must be the pinned order's own figure"


def test_reservation_moves_mass_out_of_on_hand_without_consuming_any(api):
    """PRD §3.7: "On success the reservation moves mass without creating any:
    `wire_reserved_kg` is subtracted from the heat's `on_hand_kg` and added to its
    `reserved_kg`, leaving `received_kg` untouched."
    PRD §3.7: "That figure is written to the run's `wire_reserved_kg` and is the
    value compared against the heat's `on_hand_kg` for the sufficiency gate; the
    heat's ledger is never fed into the computation, only compared against its
    result."
    PRD §2.9: "Every reservation, release and consumption posting moves mass
    between these three and never creates or destroys any."

    Design: Difficulty/combinatorial_formula/wire_reservation_pinned_rounding_order_mode_b
    """
    world, run = _run_on_certified_heat(api)

    lot = X.refresh_wire_lot(api, world.wire_lot_id)

    assert lot["received_kg"] == 500.0, (
        f"the conserved receipt figure must not move, got {lot['received_kg']}"
    )
    assert lot["reserved_kg"] == _RESERVED_KG, (
        f"the heat must hold exactly the run's reservation, got {lot['reserved_kg']}"
    )
    assert lot["on_hand_kg"] == _ON_HAND_AFTER_KG, (
        f"500.000 kg less {_RESERVED_KG} kg leaves {_ON_HAND_AFTER_KG} kg free, got "
        f"{lot['on_hand_kg']}"
    )
    assert lot["on_hand_kg"] != 281.795, (
        "the forbidden rounding order would leave 281.795 kg on hand"
    )
    assert lot["consumed_kg"] == 0.000, (
        "a reservation burns nothing, got " f"{lot['consumed_kg']}"
    )
    assert lot["reserved_kg"] == run["wire_reserved_kg"], (
        "the heat's reserved bucket and the run's reservation are one figure"
    )
    A.assert_wire_ledger_conserved(lot)


def test_a_newly_opened_run_starts_at_rest_on_both_axes(api):
    """PRD §3.7: "A newly opened run starts on both axes at rest —
    `process_status` `FAI_PENDING`, `quality_status` `OPEN`, `fai_disposition`
    `PENDING`, `heat_treat_state` `NOT_STARTED`, `peening_verified` false,
    `produced_pieces` and `scrapped_pieces` at 0, `wire_consumed_kg` at 0.000, and
    both `min_cpk_observed` and `min_ppk_observed` null."

    Design: Difficulty/combinatorial_formula/wire_reservation_pinned_rounding_order_mode_b
    """
    _, run = _run_on_certified_heat(api)

    assert run["process_status"] == C.PROCESS_FAI_PENDING, (
        "the process axis starts at FAI_PENDING, got " f"{run['process_status']!r}"
    )
    assert run["quality_status"] == C.QUALITY_OPEN, (
        "the quality axis starts at OPEN, got " f"{run['quality_status']!r}"
    )
    assert run["fai_disposition"] == C.FAI_PENDING, (
        "no first-article verdict has been taken yet, got "
        f"{run['fai_disposition']!r}"
    )
    assert run["heat_treat_state"] == C.HEAT_TREAT_NOT_STARTED
    assert run["peening_verified"] is False
    assert run["produced_pieces"] == 0
    assert run["scrapped_pieces"] == 0
    assert run["wire_consumed_kg"] == 0.000, (
        "the reservation is not a consumption, got " f"{run['wire_consumed_kg']}"
    )
    assert run["min_cpk_observed"] is None
    assert run["min_ppk_observed"] is None


# ── The quote, whose eleven steps run in one pinned order ────────────────────
# An industrial program quoted in a quantity that sits just under the first
# volume breakpoint on the pre-discount subtotal.
_INDUSTRIAL_PROGRAM = dict(
    program_code="PGM-IND-2",
    customer_name="Bramble Industrial Supply",
    application_class=C.CLASS_INDUSTRIAL,
    ppap_level=1,
    committed_pieces=100_000,
    minimum_order_quantity=2_000,
    required_salt_spray_hours=96,
    biocompatibility_required=False,
    min_fatigue_margin=1.0,
    required_ppk=1.0,
    amortization_method=C.FORECAST_BASIS,
)

_QUOTED_QTY = 2_352
_TOOL_COST_CENTS = 4_800_000
_PRE_DISCOUNT_SUBTOTAL_CENTS = 49_997
_AMORT_PER_PIECE_CENTS = 5
_UNIT_PRICE_CENTS = 26
_TOTAL_CENTS = 186_152
_FORBIDDEN_TOTAL_CENTS = 186_178


def _quote_at_the_breakpoint(api: ApiClient):
    """One DRAFT D1, one 4 800 000-cent tool, one quote for 2 352 pieces."""
    world = X.build_world(
        api,
        "design",
        program=_INDUSTRIAL_PROGRAM,
        design={"part_number": "D1-IND"},
    )
    X.capitalise_tooling(
        api,
        world.design_id,
        ENGINEERING_MANAGER_HEADERS,
        original_cost_cents=_TOOL_COST_CENTS,
    )
    version_before = world.program_version
    quoted = X.price_program(
        api,
        world.program,
        world.design_id,
        PROGRAM_MANAGER_HEADERS,
        quoted_qty=_QUOTED_QTY,
    )
    return world, quoted, version_before


def test_volume_tier_is_read_off_the_pre_discount_subtotal(api):
    """PRD §3.11: "The eleven steps below run **in this exact order**, and the
    order is pinned because the dependency looks circular: the discount tier is
    keyed on a subtotal computed before any discount or amortization, while the
    amortization cap is keyed on the unit price after the discount."
    PRD §3.11: "`quoted_pre_discount_subtotal_cents` is the base unit cost
    multiplied by `quoted_qty`, rounded to whole cents."
    PRD §3.11: "`quoted_volume_discount_pct` is read off that subtotal against the
    breakpoints 50000, 250000 and 1000000 cents: below 50000 it is 0.00, below
    250000 it is 0.03, below 1000000 it is 0.06, and at or above 1000000 it is
    0.09."
    PRD §3.11: "The comparisons are strict below and inclusive at the top tier."

    Design: Difficulty/combinatorial_formula/quote_pinned_evaluation_order_mode_c
    """
    _, quoted, _ = _quote_at_the_breakpoint(api)

    assert quoted["quoted_qty"] == _QUOTED_QTY
    assert (
        quoted["quoted_pre_discount_subtotal_cents"] == _PRE_DISCOUNT_SUBTOTAL_CENTS
    ), (
        "21.2573 mills a piece across 2 352 pieces is "
        f"{_PRE_DISCOUNT_SUBTOTAL_CENTS} cents, got "
        f"{quoted['quoted_pre_discount_subtotal_cents']}"
    )
    assert quoted["quoted_pre_discount_subtotal_cents"] < 50_000, (
        "the subtotal the tier is keyed on sits below the first breakpoint"
    )
    assert quoted["quoted_volume_discount_pct"] == 0.00, (
        "a subtotal below 50000 cents earns no discount, got "
        f"{quoted['quoted_volume_discount_pct']}"
    )
    expected = A.expected_quote(
        C.D1_WIRE_MASS_PER_PIECE_KG, 850, 1.8, _QUOTED_QTY, _TOOL_COST_CENTS
    )
    assert (
        quoted["quoted_pre_discount_subtotal_cents"]
        == expected["quoted_pre_discount_subtotal_cents"]
    ), "the subtotal must be the pinned order's own step-4 figure"
    assert (
        quoted["quoted_volume_discount_pct"] == expected["quoted_volume_discount_pct"]
    ), "the tier must be read off the step-4 subtotal, not off a later figure"


def test_amortization_cap_is_read_off_the_post_discount_unit_cost(api):
    """PRD §3.11: "The raw amortization ask is the newest tooling asset's
    `unamortized_cents` divided by `quoted_qty`, rounded **up** to the next whole
    cent."
    PRD §3.11: "The amortization cap is 0.25 of the discounted unit cost, rounded
    **down** to a whole cent."
    PRD §3.11: "`quoted_tooling_amort_per_piece_cents` is the smaller of the raw ask
    and the cap."
    PRD §3.11: "The cap exists so that tooling recovery can never dominate the piece
    price: on an expensive tool quoted in small quantity the raw ask is the binding
    value only until it crosses a quarter of the discounted unit cost."
    PRD §3.11: "`quoted_unit_price_cents` is the discounted unit cost plus that
    per-piece amortization, rounded to whole cents."

    Design: Difficulty/combinatorial_formula/quote_pinned_evaluation_order_mode_c
    """
    _, quoted, _ = _quote_at_the_breakpoint(api)

    expected = A.expected_quote(
        C.D1_WIRE_MASS_PER_PIECE_KG, 850, 1.8, _QUOTED_QTY, _TOOL_COST_CENTS
    )

    assert (
        quoted["quoted_tooling_amort_per_piece_cents"] == _AMORT_PER_PIECE_CENTS
    ), (
        "a quarter of the 21.2573-mill discounted unit cost floors to "
        f"{_AMORT_PER_PIECE_CENTS} cents, which is far below the raw ask of "
        f"{expected['raw_amortization_ask_cents']} cents, got "
        f"{quoted['quoted_tooling_amort_per_piece_cents']}"
    )
    assert (
        quoted["quoted_tooling_amort_per_piece_cents"]
        == expected["quoted_tooling_amort_per_piece_cents"]
    ), "the cap must be keyed on the discounted unit cost of step 6"
    assert (
        quoted["quoted_tooling_amort_per_piece_cents"]
        < expected["raw_amortization_ask_cents"]
    ), "the cap, not the raw ask, is the binding value on this quote"
    assert quoted["quoted_unit_price_cents"] == _UNIT_PRICE_CENTS, (
        "21.2573 mills plus 5 cents of tooling rounds to "
        f"{_UNIT_PRICE_CENTS} cents, got {quoted['quoted_unit_price_cents']}"
    )
    assert quoted["quoted_unit_price_cents"] == expected["quoted_unit_price_cents"]


def test_quote_total_follows_the_pinned_order_and_bumps_the_program_version(api):
    """PRD §3.11: "`quoted_total_cents` is `quoted_unit_price_cents` multiplied by
    `quoted_qty` plus the flat setup fee of 125000 cents."
    PRD §3.11: "Per-piece money is carried at 4 decimal places — mills — all the way
    through step 9, and only steps 4, 8, 10 and 11 land on whole cents."
    PRD §3.11: "The endpoint also increments the program's `version` by 1."

    Design: Difficulty/combinatorial_formula/quote_pinned_evaluation_order_mode_c
    """
    _, quoted, version_before = _quote_at_the_breakpoint(api)

    assert quoted["quoted_total_cents"] == _TOTAL_CENTS, (
        f"26 cents across 2 352 pieces plus the 125000-cent setup fee is "
        f"{_TOTAL_CENTS}, got {quoted['quoted_total_cents']}"
    )
    assert quoted["quoted_total_cents"] != _FORBIDDEN_TOTAL_CENTS, (
        "keying the volume tier on the amortized unit price would cross the 50000 "
        f"breakpoint and land on {_FORBIDDEN_TOTAL_CENTS}"
    )
    assert (
        quoted["quoted_total_cents"]
        == quoted["quoted_unit_price_cents"] * _QUOTED_QTY + 125_000
    ), "the total is the unit price across the quantity plus the flat setup fee"
    assert quoted["version"] == version_before + 1, (
        "pricing a program bumps its version by exactly 1, got "
        f"{quoted['version']} against {version_before}"
    )
