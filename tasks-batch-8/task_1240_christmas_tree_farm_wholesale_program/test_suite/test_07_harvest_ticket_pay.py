"""Harvest ticket payroll: per-line piece products, hourly floor, max() rule."""
from test_helpers import (
    CLOCK,
    FM,
    advance_block_to,
    advance_season_to,
    allocate_order,
    create_buyer,
    create_crew,
    create_draft_order,
    get_success_data,
    list_order_allocations,
    post_ticket,
    set_clock,
    setup_booking_season,
    submit_order,
    assert_ticket,
)


def _two_class_setup(api, counts, order_specs, crew_size):
    """BOOKING season with one lot holding `counts`; one allocated order per
    spec (height_class, quantity, unit_price_cents); season then advanced to
    HARVEST with block HARVESTABLE and one ACTIVE crew.
    Returns (ctx, crew, [allocation per spec in order])."""
    ctx = setup_booking_season(**counts)
    buyer = create_buyer()
    allocations = []
    for height_class, quantity, price in order_specs:
        order = create_draft_order(
            ctx["season"]["id"], buyer["id"], height_class=height_class,
            quantity=quantity, unit_price_cents=price,
        )
        order = submit_order(order["id"], buyer["id"])
        allocate_order(order["id"], quantity, order["version"])
        allocations.append(list_order_allocations(order["id"])[0])
    advance_block_to(ctx["block"]["id"], "HARVESTABLE")
    set_clock(CLOCK["HARVEST_DAY"])
    advance_season_to(ctx["season"]["id"], "HARVEST")
    crew = create_crew(ctx["season"]["id"], crew_code="C-1", size=crew_size)
    return ctx, crew, allocations


class TestPieceVersusHourlyFloor:
    def test_piece_and_floor_components(self, api):
        """PRD §3.5: "The piece side values each line at the per-tree piece
        rate for the line's height class — resolved through the line's
        allocation to its bucket — where the rates in cents are 180 for
        `H_4_5`, 220 for `H_5_6`, 260 for `H_6_7`, 310 for `H_7_8`, 380 for
        `H_8_9`, and 460 for `H_9_PLUS`; each line's product is rounded half-up
        to whole cents first, and the line amounts are then summed into
        `piece_total_cents`."
        PRD §3.5: "The floor side, `hourly_floor_cents`, is the crew's `size`
        multiplied by the ticket's `hours_worked` multiplied by a statutory
        minimum of 1500 cents per worker-hour."

        Design: Difficulty/combinatorial_formula/crew_pay_max_piece_vs_hourly_floor
        """
        _ctx, crew, allocs = _two_class_setup(
            api,
            {"H_6_7": 200, "H_7_8": 100},
            [("H_6_7", 100, 400), ("H_7_8", 50, 500)],
            crew_size=5,
        )
        ticket = post_ticket(
            crew, _ctx["block"]["id"],
            [
                {"allocation_id": allocs[0]["id"], "cut_count": 100},
                {"allocation_id": allocs[1]["id"], "cut_count": 50},
            ],
            work_date="2026-11-05", hours_worked=8,
        )
        assert ticket["piece_total_cents"] == 41500  # 100*260 + 50*310
        assert ticket["hourly_floor_cents"] == 60000  # 5 * 8 * 1500

    def test_gross_pay_is_max_and_floor_wins_here(self, api):
        """PRD §3.5: "The ticket's `gross_pay_cents` is the larger of the two
        sides, and `pay_basis` records which side supplied it — `PIECE` or
        `HOURLY_FLOOR` — with an exact tie resolving to `PIECE`."

        Design: Difficulty/combinatorial_formula/crew_pay_max_piece_vs_hourly_floor
        """
        _ctx, crew, allocs = _two_class_setup(
            api,
            {"H_6_7": 200, "H_7_8": 100},
            [("H_6_7", 100, 400), ("H_7_8", 50, 500)],
            crew_size=5,
        )
        ticket = post_ticket(
            crew, _ctx["block"]["id"],
            [
                {"allocation_id": allocs[0]["id"], "cut_count": 100},
                {"allocation_id": allocs[1]["id"], "cut_count": 50},
            ],
            work_date="2026-11-05", hours_worked=8,
        )
        assert_ticket(ticket)
        assert ticket["gross_pay_cents"] == 60000  # max(41500, 60000)
        assert ticket["pay_basis"] == "HOURLY_FLOOR"
        assert ticket["status"] == "POSTED", "a ticket is born POSTED"


class TestExactTieResolvesPiece:
    def test_piece_equals_floor_exactly(self, api):
        """PRD §3.5: "The piece side values each line at the per-tree piece
        rate for the line's height class — resolved through the line's
        allocation to its bucket — where the rates in cents are 180 for
        `H_4_5`, 220 for `H_5_6`, 260 for `H_6_7`, 310 for `H_7_8`, 380 for
        `H_8_9`, and 460 for `H_9_PLUS`; each line's product is rounded half-up
        to whole cents first, and the line amounts are then summed into
        `piece_total_cents`."
        PRD §3.5: "The floor side, `hourly_floor_cents`, is the crew's `size`
        multiplied by the ticket's `hours_worked` multiplied by a statutory
        minimum of 1500 cents per worker-hour."

        Design: Corner/calculations/crew_pay_exact_tie_resolves_piece
        """
        _ctx, crew, allocs = _two_class_setup(
            api,
            {"H_5_6": 100, "H_8_9": 100},
            [("H_8_9", 100, 700), ("H_5_6", 100, 400)],
            crew_size=5,
        )
        ticket = post_ticket(
            crew, _ctx["block"]["id"],
            [
                {"allocation_id": allocs[0]["id"], "cut_count": 100},
                {"allocation_id": allocs[1]["id"], "cut_count": 100},
            ],
            work_date="2026-11-05", hours_worked=8,
        )
        assert ticket["piece_total_cents"] == 60000  # 100*380 + 100*220
        assert ticket["hourly_floor_cents"] == 60000  # 5 * 8 * 1500

    def test_tie_resolves_pay_basis_to_piece(self, api):
        """PRD §3.5: "The ticket's `gross_pay_cents` is the larger of the two
        sides, and `pay_basis` records which side supplied it — `PIECE` or
        `HOURLY_FLOOR` — with an exact tie resolving to `PIECE`."

        Design: Corner/calculations/crew_pay_exact_tie_resolves_piece
        """
        _ctx, crew, allocs = _two_class_setup(
            api,
            {"H_5_6": 100, "H_8_9": 100},
            [("H_8_9", 100, 700), ("H_5_6", 100, 400)],
            crew_size=5,
        )
        ticket = post_ticket(
            crew, _ctx["block"]["id"],
            [
                {"allocation_id": allocs[0]["id"], "cut_count": 100},
                {"allocation_id": allocs[1]["id"], "cut_count": 100},
            ],
            work_date="2026-11-05", hours_worked=8,
        )
        assert ticket["gross_pay_cents"] == 60000
        assert ticket["pay_basis"] == "PIECE", "exact tie resolves to PIECE"
