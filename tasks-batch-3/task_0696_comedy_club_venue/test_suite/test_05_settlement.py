"""Box-office settlement: dual variant (public vs buyout), house-cut rounding
order, finalize cascade, deposit rounding, and finalize/open guards.

Translates the dual_variant_calc (settlement), combinatorial_formula (rounding),
transitive_cascade (finalize), and corner settlement/validation instances.
"""
import pytest

from test_helpers import (
    validate_success, validate_error,
    ApiErrorId,
    create_venue, create_draft_show,
    setup_ga_show_on_sale, setup_confirmed_buyout,
    setup_ga_show_settlement_open,
    reservation_collected, set_clock,
    TEST_USERS,
)

BOOKER = TEST_USERS["booker_headers"]
BOX_OFFICE = TEST_USERS["box_office_headers"]
FLOOR = TEST_USERS["floor_manager_headers"]


# ---------------------------------------------------------------------------
# Difficulty A — dual_variant_calc / settlement_public_vs_private_buyout
# ---------------------------------------------------------------------------
def test_settlement_private_buyout_variant(api):
    """PRD §3.12: "The `buyout_cents` is the `buyout_fee_cents` of a `CONFIRMED`
    `PrivateEvent` on the show, or zero if there is none."
    PRD §3.12: "for a bought-out show, the `buyout_fee_cents` is essentially the
    whole gross (ticket and minimum streams being near zero) and the house cut is
    taken on the buyout fee."
    PRD §3.12: "the `house_cut_cents` is computed once, as the venue's
    `house_fee_pct` multiplied by that single gross total, rounded half-up to
    whole cents".

    Design: Difficulty/dual_variant_calc/settlement_public_vs_private_buyout
    """
    ctx = setup_confirmed_buyout(
        buyout_fee_cents=500000,
        show_overrides={"title": "Corp Night", "starts_at": "2026-04-02T03:00:00Z",
                        "ends_at": "2026-04-02T05:00:00Z"},
    )
    set_clock("2026-04-02T06:00:00Z")
    settlement = validate_success(
        api.create_settlement({"show_id": ctx["show"]["id"]}, FLOOR), expected_status=201,
    )
    final = validate_success(api.finalize_settlement(settlement["id"], FLOOR))
    assert final["buyout_cents"] == 500000, \
        f"expected buyout_cents 500000, got {final['buyout_cents']}"
    assert final["gross_ticket_cents"] == 0, \
        f"expected gross_ticket_cents 0, got {final['gross_ticket_cents']}"
    # house cut = round(0.20 * 500000) == 100000.
    assert final["house_cut_cents"] == 100000, \
        f"expected house_cut_cents 100000, got {final['house_cut_cents']}"
    # net = 500000 - 100000 - 0 == 400000.
    assert final["net_to_venue_cents"] == 400000, \
        f"expected net_to_venue_cents 400000, got {final['net_to_venue_cents']}"


def test_settlement_public_variant_buyout_zero(api):
    """PRD §3.12: "The `buyout_cents` is the `buyout_fee_cents` of a `CONFIRMED`
    `PrivateEvent` on the show, or zero if there is none."
    PRD §3.12: "For a publicly sold show with no confirmed buyout, `buyout_cents`
    is zero and the gross is ticket plus minimum revenue only".

    Design: Difficulty/dual_variant_calc/settlement_public_vs_private_buyout
    """
    sc = setup_ga_show_settlement_open(
        ga_capacity=100, price_cents=4500,
        show_overrides={"title": "Public Night", "starts_at": "2026-04-20T03:00:00Z",
                        "ends_at": "2026-04-20T05:00:00Z"},
        ends_after_iso="2026-04-20T06:00:00Z",
    )
    final = validate_success(api.finalize_settlement(sc["settlement"]["id"], FLOOR))
    assert final["buyout_cents"] == 0, \
        f"public show must have buyout_cents 0, got {final['buyout_cents']}"


# ---------------------------------------------------------------------------
# Difficulty A — combinatorial_formula / settlement_house_cut_rounding_order
# ---------------------------------------------------------------------------
def test_house_cut_rounded_once_on_gross_total(api):
    """PRD §3.12: "then the `house_cut_cents` is computed once, as the venue's
    `house_fee_pct` multiplied by that single gross total, rounded half-up to
    whole cents — the round happens once on the total, never per reservation,
    because per-line rounding would drift."
    PRD §3.12: "From those included reservations, `gross_ticket_cents` is the sum
    of `ticket_charge_cents` over the rows whose `settlement_status` is
    `TICKET_PAID` or `MINIMUM_MET`".

    Design: Difficulty/combinatorial_formula/settlement_house_cut_rounding_order
    """
    venue = create_venue(name="Rounding Venue", house_fee_pct=0.25)
    show = create_draft_show(venue["id"], title="Round Night",
                             starts_at="2026-04-04T03:00:00Z", ends_at="2026-04-04T05:00:00Z")
    section = validate_success(
        api.create_section(venue["id"], show["id"], {"kind": "GA", "label": "Standing", "ga_capacity": 50}, BOOKER),
        expected_status=201,
    )
    tier = validate_success(
        api.create_tier(venue["id"], show["id"], {"section_id": section["id"], "name": "Cheap GA", "price_cents": 250}, BOOKER),
        expected_status=201,
    )
    validate_success(api.publish_show(venue["id"], show["id"], BOOKER))
    sc = {"venue": venue, "show": show, "section": section, "tier": tier}
    r1 = reservation_collected(sc, patron_id="patron-c1", party_size=1)
    r2 = reservation_collected(sc, patron_id="patron-c2", party_size=1)
    # Past doors+buffer (default 30) and past ends_at.
    set_clock("2026-04-04T06:00:00Z")
    validate_success(api.no_show(r1["id"], FLOOR))
    validate_success(api.no_show(r2["id"], FLOOR))
    settlement = validate_success(api.create_settlement({"show_id": show["id"]}, FLOOR), expected_status=201)
    final = validate_success(api.finalize_settlement(settlement["id"], FLOOR))
    # Both NO_SHOW + TICKET_PAID rows are included: gross_ticket 250+250 == 500.
    assert final["gross_ticket_cents"] == 500, \
        f"expected gross_ticket_cents 500, got {final['gross_ticket_cents']}"
    # round_half_up(0.25 * 500) once == 125 (per-line would give 126).
    assert final["house_cut_cents"] == 125, \
        f"expected house_cut_cents 125 (single round), got {final['house_cut_cents']}"
    assert final["net_to_venue_cents"] == 375, \
        f"expected net_to_venue_cents 375, got {final['net_to_venue_cents']}"


def test_house_cut_half_cent_rounds_up(api):
    """PRD §2.4: "the result is rounded to a whole number of cents using the
    round-half-up convention (a value whose fractional part is exactly one half
    rounds away from zero, upward)."
    PRD §3.12: "the `house_cut_cents` is computed once, as the venue's
    `house_fee_pct` multiplied by that single gross total, rounded half-up to
    whole cents".

    Design: Difficulty/combinatorial_formula/settlement_house_cut_rounding_order
    """
    venue = create_venue(name="HalfCent Venue", house_fee_pct=0.25)
    show = create_draft_show(venue["id"], title="HalfCent Night",
                             starts_at="2026-04-21T03:00:00Z", ends_at="2026-04-21T05:00:00Z")
    section = validate_success(
        api.create_section(venue["id"], show["id"], {"kind": "GA", "label": "Standing", "ga_capacity": 50}, BOOKER),
        expected_status=201,
    )
    tier = validate_success(
        api.create_tier(venue["id"], show["id"], {"section_id": section["id"], "name": "Penny", "price_cents": 1}, BOOKER),
        expected_status=201,
    )
    validate_success(api.publish_show(venue["id"], show["id"], BOOKER))
    sc = {"venue": venue, "show": show, "section": section, "tier": tier}
    r1 = reservation_collected(sc, patron_id="patron-h1", party_size=1)
    r2 = reservation_collected(sc, patron_id="patron-h2", party_size=1)
    set_clock("2026-04-21T06:00:00Z")
    validate_success(api.no_show(r1["id"], FLOOR))
    validate_success(api.no_show(r2["id"], FLOOR))
    settlement = validate_success(api.create_settlement({"show_id": show["id"]}, FLOOR), expected_status=201)
    final = validate_success(api.finalize_settlement(settlement["id"], FLOOR))
    assert final["gross_ticket_cents"] == 2, \
        f"expected gross_ticket_cents 2, got {final['gross_ticket_cents']}"
    # round_half_up(0.25 * 2 == 0.5) -> 1 (away from zero, upward).
    assert final["house_cut_cents"] == 1, \
        f"0.5 must round up to 1, got {final['house_cut_cents']}"
    assert final["net_to_venue_cents"] == 1, \
        f"expected net 2 - 1 == 1, got {final['net_to_venue_cents']}"


# ---------------------------------------------------------------------------
# Difficulty A — transitive_cascade / settlement_finalize_cascade_depth2_to_venue
# ---------------------------------------------------------------------------
def test_finalize_cascades_show_settled_and_venue_open(api):
    """PRD §3.12: "Finalizing sets `status` to `FINALIZED`, moves the show to
    `SETTLED`, and recomputes the venue's `posture` — back to `OPEN` if no other
    show remains `SETTLING`."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascade_depth2_to_venue
    """
    sc = setup_ga_show_settlement_open(
        ga_capacity=100, price_cents=4500,
        show_overrides={"title": "Final Night", "starts_at": "2026-04-08T03:00:00Z",
                        "ends_at": "2026-04-08T05:00:00Z"},
        ends_after_iso="2026-04-08T06:00:00Z",
    )
    final = validate_success(api.finalize_settlement(sc["settlement"]["id"], FLOOR))
    assert final["status"] == "FINALIZED", f"expected FINALIZED, got {final['status']}"
    show = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert show["status"] == "SETTLED", f"show must cascade to SETTLED, got {show['status']}"
    venue = validate_success(api.get_venue(sc["venue"]["id"], BOOKER))
    assert venue["posture"] == "OPEN", \
        f"venue posture must recompute to OPEN, got {venue['posture']}"


def test_open_settlement_moves_show_settling_and_posture_reconciling(api):
    """PRD §3.12: "Opening starts the settlement `OPEN`, moves the show to
    `SETTLING`, recomputes the venue's `posture` to `RECONCILING`, and blocks any
    new reservation for that show."

    Design: Difficulty/transitive_cascade/settlement_finalize_cascade_depth2_to_venue
    """
    sc = setup_ga_show_settlement_open(
        ga_capacity=100, price_cents=4500,
        show_overrides={"title": "Open Night", "starts_at": "2026-04-22T03:00:00Z",
                        "ends_at": "2026-04-22T05:00:00Z"},
        ends_after_iso="2026-04-22T06:00:00Z",
    )
    show = validate_success(api.get_show(sc["show"]["id"], BOOKER))
    assert show["status"] == "SETTLING", \
        f"opening settlement must move show to SETTLING, got {show['status']}"
    venue = validate_success(api.get_venue(sc["venue"]["id"], BOOKER))
    assert venue["posture"] == "RECONCILING", \
        f"venue posture must become RECONCILING, got {venue['posture']}"


# ---------------------------------------------------------------------------
# Corner B — calculations / buyout_deposit_round_half_up
# ---------------------------------------------------------------------------
def test_buyout_deposit_round_half_up(api):
    """PRD §3.11: "computes its `deposit_cents` as the `deposit_pct` multiplied by
    `buyout_fee_cents` rounded half-up to whole cents".
    PRD §2.4: "Where a calculation multiplies a fractional rate by a cent amount,
    such as a deposit percentage or the house cut, the result is rounded to a
    whole number of cents using the round-half-up convention".

    Design: Corner/calculations/buyout_deposit_round_half_up
    """
    venue = create_venue(name="Dep Venue")
    show = create_draft_show(venue["id"], title="Dep Night",
                             starts_at="2026-05-12T03:00:00Z", ends_at="2026-05-12T05:00:00Z")
    pe = validate_success(
        api.create_private_event(
            {"show_id": show["id"], "client_name": "Epsilon",
             "buyout_fee_cents": 333333, "deposit_pct": 0.25},
            BOOKER,
        ),
        expected_status=201,
    )
    # 0.25 * 333333 == 83333.25 -> round_half_up -> 83333.
    assert pe["deposit_cents"] == 83333, \
        f"expected deposit_cents 83333, got {pe['deposit_cents']}"


# ---------------------------------------------------------------------------
# Corner B — validations / settlement guards
# ---------------------------------------------------------------------------
def test_settlement_open_before_show_ended_rejected(api):
    """PRD §3.12: "Opening is allowed only once the logical clock has reached the
    show's `ends_at` — an attempt before then is rejected with
    `ERR_SHOW_NOT_ENDED`".

    Design: Corner/validations/settlement_open_before_show_ended
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "NotEnded Night", "starts_at": "2026-05-17T03:00:00Z",
                        "ends_at": "2026-05-17T05:00:00Z"},
    )
    # Clock remains at startup default 2026-03-01, before the show's ends_at.
    resp = api.create_settlement({"show_id": sc["show"]["id"]}, FLOOR)
    validate_error(resp, ApiErrorId.ERR_SHOW_NOT_ENDED)


def test_duplicate_open_settlement_rejected(api):
    """PRD §3.12: "and only when no `OPEN` settlement already exists for the show,
    a duplicate being rejected with `ERR_SETTLEMENT_EXISTS`."

    Design: Corner/validations/duplicate_open_settlement_rejected
    """
    sc = setup_ga_show_settlement_open(
        show_overrides={"title": "DupSettle Night", "starts_at": "2026-05-20T03:00:00Z",
                        "ends_at": "2026-05-20T05:00:00Z"},
        ends_after_iso="2026-05-20T06:00:00Z",
    )
    resp = api.create_settlement({"show_id": sc["show"]["id"]}, FLOOR)
    validate_error(resp, ApiErrorId.ERR_SETTLEMENT_EXISTS)


def test_finalize_blocked_by_unmet_minimum(api):
    """PRD §3.12: "if any reservation for the show is `CHECKED_IN` and
    `TICKET_PAID` while its `items_consumed_cents` is still below its
    `minimum_due_cents`, finalization is blocked with `ERR_MINIMUM_NOT_MET`."

    Design: Corner/validations/finalize_blocked_by_unmet_minimum
    """
    sc = setup_ga_show_on_sale(
        show_overrides={"title": "MinUnmet Night", "starts_at": "2026-05-19T03:00:00Z",
                        "ends_at": "2026-05-19T05:00:00Z"},
    )
    res = reservation_collected(sc, patron_id="patron-mu", party_size=2)
    validate_success(api.check_in(res["id"], BOX_OFFICE))
    set_clock("2026-05-19T06:00:00Z")
    settlement = validate_success(api.create_settlement({"show_id": sc["show"]["id"]}, FLOOR), expected_status=201)
    resp = api.finalize_settlement(settlement["id"], FLOOR)
    validate_error(resp, ApiErrorId.ERR_MINIMUM_NOT_MET)
