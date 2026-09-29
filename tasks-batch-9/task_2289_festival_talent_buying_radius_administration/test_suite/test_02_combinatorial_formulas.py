"""Multi-input formulas: the guarantee ceiling, per-line rider rounding and the
pinned settlement order.

Every test builds its own world from an empty database and parks the logical
clock before any temporal rule is consulted.
"""

from decimal import Decimal

import pytest
from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import (
    FINANCE_CONTROLLER,
    PRODUCTION_MANAGER,
    TALENT_BUYER,
    expected_line_cost_cents,
    expected_promoter_share_pct,
    expected_settlement_total_cents,
)
from test_helpers import fixtures as fx
from test_helpers.constants import BASE_FLOOR_CENTS, DRAW_UNIT_CENTS
from test_helpers.factories import offer_payload


# --------------------------------------------------------------------------
# Composite state builders used by the tests below.
# --------------------------------------------------------------------------
def _edition_with_two_headliners_and_three_drafts(api):
    """Three-tier edition carrying 3000000 of ELECTRONIC commitment.

    Two ELECTRONIC headliners are accepted at 1500000 each, then three offers
    are drafted on the 2026-12-06 programming day of the flagship stage: a
    draw-4 ELECTRONIC act, a draw-95 ROCK act and a draw-95 HIP_HOP act.
    """
    ctx = fx.three_tier_edition(api)
    glass_harbor = fx.create_artist(
        api,
        legal_name="Glass Harbor Inc",
        performing_name="Glass Harbor",
        primary_genre="ELECTRONIC",
        agency="Meridian Talent",
        draw_score=72,
        default_radius_miles=150,
    )
    tidal_kid = fx.create_artist(
        api,
        legal_name="Tidal Kid LLC",
        performing_name="Tidal Kid",
        primary_genre="ELECTRONIC",
        agency="Foghorn Agency",
        draw_score=4,
        default_radius_miles=50,
    )
    ironvale = fx.create_artist(
        api,
        legal_name="Ironvale Touring",
        performing_name="Ironvale",
        primary_genre="ROCK",
        agency="Foghorn Agency",
        draw_score=95,
        default_radius_miles=200,
    )
    cass_meridian = fx.create_artist(
        api,
        legal_name="Cass Meridian LLC",
        performing_name="Cass Meridian",
        primary_genre="HIP_HOP",
        agency="Foghorn Agency",
        draw_score=95,
        default_radius_miles=200,
    )

    fx.accepted_booking(
        api,
        ctx,
        ctx["artist"],
        guarantee_cents=1500000,
        billing_position=1,
        slot_start_utc="2026-12-04T21:00:00Z",
    )
    fx.accepted_booking(
        api,
        ctx,
        glass_harbor,
        guarantee_cents=1500000,
        billing_position=1,
        slot_start_utc="2026-12-05T21:00:00Z",
    )

    festival_id = ctx["festival"]["id"]
    stage_id = ctx["stage"]["id"]
    low_draw_offer = validate_success(
        api.create_offer(
            offer_payload(
                festival_id,
                tidal_kid["id"],
                ctx["emerging"]["id"],
                stage_id,
                guarantee_cents=425000,
                billing_position=2,
                slot_start_utc="2026-12-06T17:00:00Z",
                radius_miles=50,
                window_start_date="2026-11-04",
                window_end_date="2026-12-14",
                exclusivity_scope="TICKETED_ONLY",
            ),
            TALENT_BUYER,
        ),
        201,
    )
    rock_offer = validate_success(
        api.create_offer(
            offer_payload(
                festival_id,
                ironvale["id"],
                ctx["emerging"]["id"],
                stage_id,
                guarantee_cents=1900000,
                billing_position=3,
                slot_start_utc="2026-12-06T19:00:00Z",
                radius_miles=200,
                window_start_date="2026-11-04",
                window_end_date="2026-12-14",
                exclusivity_scope="FULL",
            ),
            TALENT_BUYER,
        ),
        201,
    )
    hip_hop_offer = validate_success(
        api.create_offer(
            offer_payload(
                festival_id,
                cass_meridian["id"],
                ctx["mid_card"]["id"],
                stage_id,
                guarantee_cents=2375001,
                billing_position=4,
                slot_start_utc="2026-12-06T15:00:00Z",
                radius_miles=200,
                window_start_date="2026-11-04",
                window_end_date="2026-12-14",
                exclusivity_scope="FULL",
            ),
            TALENT_BUYER,
        ),
        201,
    )
    return {
        "ctx": ctx,
        "low_draw_offer": low_draw_offer,
        "rock_offer": rock_offer,
        "hip_hop_offer": hip_hop_offer,
    }


def _booking_with_four_travel_and_hospitality_lines(api):
    """Accepted booking at 1500000 with three identical TRAVEL lines and one
    HOSPITALITY line; every line but the third travel leg is already approved."""
    ctx = fx.single_tier_edition(api)
    booking = fx.accepted_booking(api, ctx, guarantee_cents=1500000)
    artist_id = ctx["artist"]["id"]
    travel_legs = [
        fx.add_rider_line(
            api,
            booking["id"],
            artist_id,
            category="TRAVEL",
            description=f"Tour bus day rate leg {leg}",
            quantity=1,
            unit_cost_cents=62512,
            is_promoter_provided=False,
        )
        for leg in (1, 2, 3)
    ]
    hospitality = fx.add_rider_line(
        api,
        booking["id"],
        artist_id,
        category="HOSPITALITY",
        description="Green room supply run",
        quantity=3,
        unit_cost_cents=33333,
        is_promoter_provided=False,
    )
    fx.decide_rider_line(api, travel_legs[0]["id"], "APPROVED")
    fx.decide_rider_line(api, travel_legs[1]["id"], "APPROVED")
    fx.decide_rider_line(api, hospitality["id"], "APPROVED")
    return {
        "booking": booking,
        "travel_legs": travel_legs,
        "hospitality": hospitality,
    }


def _booking_with_contracted_rider_of_640243(api):
    """Accepted booking at 1500000 whose contracted rider scope lands on 640243.

    A plain technical approval, a capped hospitality approval and a travel line
    substituted down to 71501 per unit.
    """
    ctx = fx.single_tier_edition(api)
    booking = fx.accepted_booking(api, ctx, guarantee_cents=1500000)
    artist_id = ctx["artist"]["id"]
    technical = fx.add_rider_line(
        api,
        booking["id"],
        artist_id,
        category="TECHNICAL",
        description="Line array supplement",
        quantity=2,
        unit_cost_cents=125000,
        is_promoter_provided=False,
    )
    hospitality = fx.add_rider_line(
        api,
        booking["id"],
        artist_id,
        category="HOSPITALITY",
        description="Dressing room build-out",
        quantity=4,
        unit_cost_cents=60000,
        is_promoter_provided=False,
    )
    travel = fx.add_rider_line(
        api,
        booking["id"],
        artist_id,
        category="TRAVEL",
        description="Crew ground transfers",
        quantity=3,
        unit_cost_cents=83333,
        is_promoter_provided=False,
    )
    fx.decide_rider_line(api, technical["id"], "APPROVED")
    fx.decide_rider_line(api, hospitality["id"], "APPROVED")
    fx.decide_rider_line(
        api, travel["id"], "SUBSTITUTED", substitute_unit_cost_cents=71501
    )
    return {"booking": booking}


# --------------------------------------------------------------------------
# the guarantee ceiling
# --------------------------------------------------------------------------
def test_low_draw_offer_ceiling_binds_on_the_scaled_draw_floor(api):
    """The draw floor wins the inner maximum and the scaled draw wins the outer minimum.

    "Step four converts draw into money: the draw component is the greater of a floor of 500000 cents — five thousand dollars, the least the system will ever consider an act worth — and the act's `draw_score` multiplied by 25000 cents, meaning two hundred and fifty dollars of headroom for every point of draw."
    "Step five scales that draw component by the genre balance factor and **floors** the product to whole cents; this is the only rounding step in the whole computation, applied once at the end rather than per input."
    "Computed **excluding** the offer under evaluation, the share picks the factor: `genre_balance_factor` is stamped at 1.00 when the share is at most 0.30, at 0.85 when the share is above 0.30 but at most 0.40, and at 0.60 when the share is above 0.40."

    Design: Difficulty/combinatorial_formula/guarantee_ceiling_nested_min_max
    """
    state = _edition_with_two_headliners_and_three_drafts(api)

    issued = validate_success(
        api.issue_offer(state["low_draw_offer"]["id"], TALENT_BUYER)
    )

    assert issued["status"] == "ISSUED"
    assert issued["genre_balance_factor"] == pytest.approx(0.85)
    assert issued["guarantee_ceiling_cents"] == 425000
    # The floor of 500000 beat the draw-4 product of 100000 inside the maximum,
    # and the scaling was floored once at the end.
    draw_component = max(BASE_FLOOR_CENTS, 4 * DRAW_UNIT_CENTS)
    assert issued["guarantee_ceiling_cents"] == int(
        Decimal(draw_component) * Decimal("0.85")
    )


def test_rock_offer_ceiling_binds_on_tier_headroom(api):
    """An untouched genre keeps the factor at 1.00 and the tier headroom binds instead.

    "Step six sets `guarantee_ceiling_cents` to the smallest of the tier headroom, the festival headroom and the scaled draw component."

    Design: Difficulty/combinatorial_formula/guarantee_ceiling_nested_min_max
    """
    state = _edition_with_two_headliners_and_three_drafts(api)
    validate_success(api.issue_offer(state["low_draw_offer"]["id"], TALENT_BUYER))

    issued = validate_success(api.issue_offer(state["rock_offer"]["id"], TALENT_BUYER))

    assert issued["status"] == "ISSUED"
    assert issued["genre_balance_factor"] == pytest.approx(1.00)
    assert issued["guarantee_ceiling_cents"] == 1900000


def test_offer_one_cent_above_the_scaled_draw_ceiling_is_refused(api):
    """One cent over the smallest of the three headrooms is refused and stays a draft.

    "An offer whose `guarantee_cents` plus `production_fee_cents` exceeds that ceiling is refused with `ERR_GUARANTEE_CEILING_EXCEEDED`; equality with the ceiling passes."

    Design: Difficulty/combinatorial_formula/guarantee_ceiling_nested_min_max
    """
    state = _edition_with_two_headliners_and_three_drafts(api)
    validate_success(api.issue_offer(state["low_draw_offer"]["id"], TALENT_BUYER))
    validate_success(api.issue_offer(state["rock_offer"]["id"], TALENT_BUYER))

    validate_error(
        api.issue_offer(state["hip_hop_offer"]["id"], TALENT_BUYER),
        "ERR_GUARANTEE_CEILING_EXCEEDED",
        422,
    )

    unchanged = validate_success(
        api.get_offer(state["hip_hop_offer"]["id"], TALENT_BUYER)
    )
    assert unchanged["status"] == "DRAFT"
    assert unchanged["guarantee_cents"] == 2375001


# --------------------------------------------------------------------------
# per-line rider rounding
# --------------------------------------------------------------------------
def test_travel_rider_lines_round_per_line_before_summation(api):
    """Three identical escalated legs round one by one, not after summing.

    "Each line's own cost is computed the same way in both scopes and is rounded **per line, before any summation** — summing raw products and rounding the total once at the end is the wrong reading and yields a different figure."
    "Travel lines carry a twelve percent escalation to cover fare drift; lines in the other two categories carry none."

    Design: Difficulty/combinatorial_formula/rider_per_line_rounding_order
    """
    state = _booking_with_four_travel_and_hospitality_lines(api)

    decided = validate_success(
        api.decide_rider_item(
            state["travel_legs"][2]["id"], {"decision": "APPROVED"}, PRODUCTION_MANAGER
        )
    )
    assert decided["line_cost_cents"] == 70013
    for leg in state["travel_legs"]:
        line = validate_success(api.get_rider_item(leg["id"], TALENT_BUYER))
        assert line["line_cost_cents"] == 70013
        assert line["line_cost_cents"] == expected_line_cost_cents(1, 62512, "TRAVEL")

    hospitality = validate_success(
        api.get_rider_item(state["hospitality"]["id"], TALENT_BUYER)
    )
    assert hospitality["line_cost_cents"] == 99999

    estimate = validate_success(
        api.get_rider_estimate(
            state["booking"]["id"], PRODUCTION_MANAGER, {"variant": "BOTH"}
        )
    )
    assert estimate["contracted_scope_cents"] == 310038
    assert estimate["proposed_scope_cents"] == 310038
    assert estimate["contracted_scope_cents"] != 310039
    assert estimate["priced_line_count"] == 4
    assert estimate["capped_line_count"] == 0
    assert estimate["zeroed_line_count"] == 0


def test_rider_settles_once_the_last_proposed_line_is_decided(api):
    """The booking mirrors the per-line total and leaves PENDING_RIDER.

    "In all three branches, when the decision leaves no line of that booking still `PROPOSED` and the booking has at least one rider line, the booking's `contract_status` moves `PENDING_RIDER → RIDER_SETTLED`."

    Design: Difficulty/combinatorial_formula/rider_per_line_rounding_order
    """
    state = _booking_with_four_travel_and_hospitality_lines(api)
    fx.decide_rider_line(api, state["travel_legs"][2]["id"], "APPROVED")

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))
    assert booking["rider_estimate_cents"] == 310038
    assert booking["contract_status"] == "RIDER_SETTLED"


# --------------------------------------------------------------------------
# the pinned settlement order
# --------------------------------------------------------------------------
def test_settlement_share_bracket_reads_the_unadjusted_gross(api):
    """The bracket is chosen from the gross that still carries the whole rider.

    "The order is: take the booking's `rider_estimate_cents`, which is the contracted-scope rider total; take the `waiver_fee_cents` of the booking's clause, or 0 when the booking has no clause row; form the pre-share gross as `guarantee_cents` plus that rider figure plus that waiver fee, using the **unadjusted** rider on purpose; select the promoter share from that pre-share gross — 0.60 when the gross has reached 5000000 cents (fifty thousand dollars), 0.75 when it has reached 2000000 cents (twenty thousand dollars) but is below the higher bracket, and 0.90 when it is below 2000000 cents; compute the reimbursed rider as the rider figure multiplied by that share, rounded half up once; and finally set `settlement_total_cents` to `guarantee_cents` plus the reimbursed rider plus the waiver fee, less `deposit_paid_cents`."

    Design: Difficulty/combinatorial_formula/settlement_share_bracket_evaluation_order
    """
    state = _booking_with_contracted_rider_of_640243(api)

    settlement = validate_success(
        api.get_settlement(state["booking"]["id"], FINANCE_CONTROLLER)
    )

    assert settlement["guarantee_cents"] == 1500000
    assert settlement["rider_estimate_cents"] == 640243
    assert settlement["waiver_fee_cents"] == 0
    assert settlement["gross_pre_share_cents"] == 2140243
    assert settlement["promoter_share_pct"] == pytest.approx(0.75)
    assert settlement["promoter_share_pct"] == pytest.approx(
        expected_promoter_share_pct(2140243)
    )
    assert settlement["reimbursed_rider_cents"] == 480182
    assert settlement["deposit_paid_cents"] == 0
    assert settlement["settlement_total_cents"] == 1980182


def test_booking_settlement_total_rejects_the_circular_bracket_reading(api):
    """The stamped total is the pinned one, not the share-adjusted re-bracketing.

    "Selecting the bracket from a share-adjusted rider — the circular reading — changes the answer whenever the gross sits near a bracket edge, and is wrong."

    Design: Difficulty/combinatorial_formula/settlement_share_bracket_evaluation_order
    """
    state = _booking_with_contracted_rider_of_640243(api)

    booking = validate_success(api.get_booking(state["booking"]["id"], TALENT_BUYER))

    assert booking["rider_estimate_cents"] == 640243
    assert booking["settlement_total_cents"] == 1980182
    assert booking["settlement_total_cents"] == expected_settlement_total_cents(
        1500000, 640243, 0, 0
    )
    assert booking["settlement_total_cents"] != 2076219
