"""Three loads of identical tonnage that differ only in their lab readings, probing
every closed-interval edge of the four gated quality components at once."""
from test_helpers import (
    capture_gross,
    capture_tare,
    list_settlement_lines,
    move_clock,
    read_contract,
    read_weigh_tag,
    record_grading,
    setup_harvest_ready,
    setup_scheduled_appointment,
    single_installment_plan,
)

DELIVERY_WINDOW = ("2026-08-25T14:00:00Z", "2026-08-25T18:00:00Z")
ARRIVAL_AT = "2026-08-25T14:30:00Z"
GROSS_WEIGHT_LBS = 61240
TARE_WEIGHT_LBS = 17240

BOUNDARY_SPEC = {
    "min_brix_accept": 20.0,
    "brix_penalty_start": 22.0,
    "brix_bonus_start": 24.0,
    "brix_step": 0.5,
    "brix_bonus_pct_per_step": 1.5,
    "brix_penalty_pct_per_step": 2.0,
    "ta_min_gl": 5.5,
    "ta_max_gl": 9.0,
    "acid_out_of_spec_penalty_pct": 3.0,
    "rot_free_pct": 2.0,
    "rot_penalty_pct_per_point": 1.5,
    "rot_rejection_pct": 8.0,
    "mog_max_pct": 1.0,
    "mog_penalty_pct": 2.5,
    "max_total_bonus_pct": 8.0,
    "max_total_penalty_pct": 20.0,
}

# Every reading sits exactly on an edge, one tenth past an edge, or one tenth inside
# the penalty region; the tonnage is deliberately identical on all three loads.
READINGS = (
    {"brix": 24.0, "ta_gl": 5.5, "ph": 3.50, "rot_pct": 2.0, "mog_pct": 1.0},
    {"brix": 24.5, "ta_gl": 5.5, "ph": 3.50, "rot_pct": 2.9, "mog_pct": 1.0},
    {"brix": 21.9, "ta_gl": 5.4, "ph": 3.20, "rot_pct": 3.0, "mog_pct": 1.1},
)


def _three_boundary_loads() -> dict:
    """Three 22.000-ton loads on one slot of a 66.000-ton contract, each graded on a
    different set of boundary readings."""
    ctx = setup_harvest_ready(
        contract_overrides={
            "contract_basis": "TONNAGE",
            "base_price_per_ton_cents": 450000,
            "committed_tons": 66.000,
            "over_delivery_policy": "ACCEPT_AT_SPOT",
            "settlement_basis": "LOAD_BY_LOAD",
            "installment_plan": single_installment_plan(),
        },
        lane_overrides={
            "lane_code": "L1",
            "daily_capacity_tons": 80.000,
            "turnaround_buffer_minutes": 30,
            "max_load_tons": 70.0,
        },
        estimated_tons=66.000,
        block_overrides={"acres": 35.000},
        spec_overrides=dict(BOUNDARY_SPEC),
    )
    setup_scheduled_appointment(ctx, DELIVERY_WINDOW[0], DELIVERY_WINDOW[1], planned_tons=66.000)
    move_clock(ARRIVAL_AT)

    # All three trucks present and tare before any of them is graded.  The slot closes
    # as soon as "every weigh tag of an arrived appointment has reached `NET_FINAL` and
    # holds a disposition other than `PENDING` or `DISPUTED`", so grading load one while
    # loads two and three were still to arrive would shut the slot under them.
    open_tags = []
    for _ in READINGS:
        tag = capture_gross(ctx["appointment"]["id"], ctx["block"]["id"], GROSS_WEIGHT_LBS)
        capture_tare(tag["id"], TARE_WEIGHT_LBS)
        open_tags.append(tag)

    tags, gradings = [], []
    for tag, readings in zip(open_tags, READINGS):
        gradings.append(record_grading(tag["id"], **readings))
        tags.append(read_weigh_tag(tag["id"]))
    ctx["tags"] = tags
    ctx["gradings"] = gradings
    return ctx


def _line(ctx: dict, index: int) -> dict:
    lines = list_settlement_lines(weigh_tag_id=ctx["tags"][index]["id"])
    assert len(lines) == 1, f"expected one settlement line on load {index + 1}, got {len(lines)}"
    return lines[0]


def test_readings_exactly_on_every_edge_contribute_nothing():
    """Brix exactly at `brix_bonus_start`, acidity exactly at `ta_min_gl`, rot exactly
    at `rot_free_pct` and MOG exactly at `mog_max_pct` all fall in their dead bands.

    PRD: "Between the two thresholds — from `brix_penalty_start` up to and including
    `brix_bonus_start` — lies a dead band in which `brix_component_pct` is 0.0."

    Design: Difficulty/boundary_precision_check/brix_dead_band_and_sub_step_exact_boundaries
    """
    ctx = _three_boundary_loads()
    grading = ctx["gradings"][0]

    assert float(grading["brix_component_pct"]) == 0.0
    assert float(grading["acid_component_pct"]) == 0.0
    assert float(grading["rot_component_pct"]) == 0.0
    assert float(grading["mog_component_pct"]) == 0.0
    assert float(grading["raw_adjustment_pct"]) == 0.0
    assert float(grading["adjustment_pct"]) == 0.0


def test_an_unadjusted_load_is_priced_at_the_bare_base():
    """With every component silent the per-ton price is the contract's base, and the
    provisional payment is 60 percent of the rounded gross.

    PRD: "Fourth, `provisional_amount_cents` is `gross_amount_cents` multiplied by the
    contract's `provisional_payment_pct` divided by 100, rounded half up to whole cents."

    Design: Difficulty/boundary_precision_check/brix_dead_band_and_sub_step_exact_boundaries
    """
    ctx = _three_boundary_loads()
    line = _line(ctx, 0)

    assert line["price_per_ton_cents"] == 450000
    assert line["gross_amount_cents"] == 9900000
    assert line["provisional_amount_cents"] == 5940000


def test_one_step_past_the_bonus_edge_pays_while_a_partial_rot_point_does_not():
    """Brix 24.5 is exactly one 0.5 step above the bonus edge and earns 1.5 points;
    rot 2.9 is 0.9 above the free allowance and earns nothing, because only whole
    points are billed.

    PRD: "A reading of 5.5 against a `rot_free_pct` of 2.0 therefore charges 3 whole
    points, not 3.5 — only completed points are billed."

    Design: Difficulty/boundary_precision_check/brix_dead_band_and_sub_step_exact_boundaries
    """
    ctx = _three_boundary_loads()
    grading = ctx["gradings"][1]

    assert float(grading["brix_component_pct"]) == 1.5
    assert float(grading["rot_component_pct"]) == 0.0
    assert float(grading["acid_component_pct"]) == 0.0
    assert float(grading["mog_component_pct"]) == 0.0
    assert float(grading["adjustment_pct"]) == 1.5

    line = _line(ctx, 1)
    assert line["price_per_ton_cents"] == 456750
    assert line["gross_amount_cents"] == 10048500


def test_a_tenth_inside_the_penalty_region_still_charges_no_sugar_penalty():
    """Brix 21.9 is below `brix_penalty_start` yet not a full 0.5 step below it, so the
    sugar component stays silent while the other three components all fire.

    PRD: "When instead the tenths of `brix` fall below the tenths of
    `brix_penalty_start`, the number of complete penalty steps is the difference between
    the tenths of `brix_penalty_start` and the tenths of `brix`, divided by the tenths of
    `brix_step` and rounded down to a whole number"

    Design: Difficulty/boundary_precision_check/brix_dead_band_and_sub_step_exact_boundaries
    """
    ctx = _three_boundary_loads()
    grading = ctx["gradings"][2]

    assert float(grading["brix_component_pct"]) == 0.0
    assert float(grading["acid_component_pct"]) == -3.0
    assert float(grading["rot_component_pct"]) == -1.5
    assert float(grading["mog_component_pct"]) == -2.5
    assert float(grading["adjustment_pct"]) == -7.0

    line = _line(ctx, 2)
    assert line["price_per_ton_cents"] == 418500
    assert line["gross_amount_cents"] == 9207000


def test_none_of_the_boundary_loads_is_condemned():
    """Rejection is decided from the raw readings, and none of the three crosses the
    acceptance floor or the rot ceiling.

    PRD: "it is `REJECT_QUALITY` when the tenths of `brix` fall below the tenths of
    `min_brix_accept`, or when the tenths of `rot_pct` reach or exceed the tenths of
    `rot_rejection_pct`; otherwise it is `ACCEPT`."

    Design: Difficulty/boundary_precision_check/brix_dead_band_and_sub_step_exact_boundaries
    """
    ctx = _three_boundary_loads()

    for index in range(3):
        tag = read_weigh_tag(ctx["tags"][index]["id"])
        assert float(tag["net_tons"]) == 22.000, f"load {index + 1} lost its tonnage"
        assert tag["disposition"] == "ACCEPTED", f"load {index + 1} was not accepted"
        assert ctx["gradings"][index]["recommended_disposition"] == "ACCEPT"


def test_the_three_boundary_loads_fill_the_soft_cap_exactly():
    """66.000 tons against a 66.000-ton soft cap reaches the cap, and the contract's
    provisional money is the sum of three differently priced lines.

    PRD: "`CAP_REACHED` once `delivered_contract_tons` reaches or exceeds
    `contract_cap_tons`"

    Design: Difficulty/boundary_precision_check/brix_dead_band_and_sub_step_exact_boundaries
    """
    ctx = _three_boundary_loads()
    contract = read_contract(ctx["contract"]["id"])

    assert float(contract["delivered_contract_tons"]) == 66.000
    assert float(contract["delivered_over_tons"]) == 0.000
    assert contract["tonnage_status"] == "CAP_REACHED"
    assert contract["provisional_settlement_cents"] == 17493300
