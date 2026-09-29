"""Optimistic concurrency on the five contested parents a second writer can
legitimately move: a round's session grid, a wall's occupancy, the award budget,
the acceptance capacity and the settlement ledger. In each case the first write
from a shared read succeeds, the second is refused at 412 even though its own
business check would pass, and the re-read retry goes through unchanged."""

import pytest

from test_helpers import (
    FINANCE_A,
    FINANCE_B,
    JURY_CHAIR_A,
    JURY_CHAIR_B,
    REGISTRAR,
    ApiErrorId,
    create_assignment_payload,
    create_installation_plan_payload,
    fixtures,
    validate_error,
    validate_success,
)

# ─── Sessions ─────────────────────────────────────────

FIRST_SESSION = ("2026-10-06T09:00:00Z", "2026-10-06T13:00:00Z")
SECOND_SESSION = ("2026-10-07T09:00:00Z", "2026-10-07T11:00:00Z")

# ─── Walls ────────────────────────────────────────────

TWO_WORKS = [fixtures.WORK_RIDGE_LINE, fixtures.WORK_SALT_FLAT]
FIRST_SPAN = (0.0, 100.0)
SECOND_SPAN = (300.0, 400.0)
FIRST_WORK_WEIGHT_KG = 6.0
SECOND_WORK_WEIGHT_KG = 5.0
WALL_LENGTH_CM = 600.0

# ─── Awards ───────────────────────────────────────────

COUNCIL_AWARD_BUDGET_CENTS = 500000
HALF_BUDGET_PRIZE_CENTS = 200000

# ─── Promotion ────────────────────────────────────────

# Four paintings, so the per-medium cap — ceil(5 * 0.40) = 2 — binds while the
# global acceptance capacity of 5 is still wide open.
FOUR_PAINTINGS = [
    {
        "title": "Ridge Line", "medium_category": "PAINTING",
        "width_cm": 90.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 6.0,
        "declared_value_cents": 400000,
    },
    {
        "title": "Salt Flat", "medium_category": "PAINTING",
        "width_cm": 100.0, "height_cm": 70.0, "depth_cm": 4.0, "weight_kg": 5.0,
        "declared_value_cents": 300000,
    },
    {
        "title": "Low Tide", "medium_category": "PAINTING",
        "width_cm": 80.0, "height_cm": 60.0, "depth_cm": 4.0, "weight_kg": 4.0,
        "declared_value_cents": 200000,
    },
    {
        "title": "Dry Creek", "medium_category": "PAINTING",
        "width_cm": 70.0, "height_cm": 50.0, "depth_cm": 4.0, "weight_kg": 3.0,
        "declared_value_cents": 100000,
    },
]
FOUR_CARDS = [(9, 9, 9), (8, 9, 9), (8, 8, 8), (7, 8, 8)]
FOUR_CERTIFIED_MEANS = [9.00, 8.60, 8.00, 7.60]
WIDE_CAPACITY = {"acceptance_capacity": 5, "waitlist_capacity": 2}
MEDIUM_CAP = 2

# ─── Payouts ──────────────────────────────────────────

SALE_PRICE_CENTS = 250000
ARTIST_PAYABLE_CENTS = 149425
TWO_PAYABLES_CENTS = 298850


# ─── A round's session grid ────────────────────────────

def test_a_second_booking_from_one_read_of_the_round_is_refused(api):
    """PRD §2.7: "Booking a juror session requires `expected_jury_round_version`,
    matching the `JuryRound`'s current `version`. Booking a different juror or a
    non-overlapping session legitimately succeeds and advances the round, so a
    stale quote means the chair is scheduling against a session grid that has
    already changed."

    PRD §2.7: "If the quoted value does not equal the parent's current `version`,
    the request is rejected with `ERR_STALE_VERSION` (HTTP 412) and nothing is
    written."

    PRD §3.4: "A juror's `assignment_count` counts the same `BOOKED` and
    `COMPLETED` set."

    Design: Corner/cross_cutting_layers/occ_assignment_create_stale_jury_round_version_rejected
    """
    exhibition = fixtures.open_call()
    fixtures.enter_jurying(exhibition["id"])
    first_juror = fixtures.invite_and_confirm_juror(
        display_name="Iris Vega", email="iris.vega@example.org"
    )
    second_juror = fixtures.invite_and_confirm_juror(
        display_name="Omar Fell", email="omar.fell@example.org",
        honorarium_cents=40000,
    )
    jury_round = fixtures.create_jury_round(
        exhibition["id"], quorum_required=2
    )
    read_once = jury_round["version"]

    booked = validate_success(
        api.create_juror_assignment(
            jury_round["id"],
            create_assignment_payload(
                first_juror["id"], read_once,
                session_start_at=FIRST_SESSION[0],
                session_end_at=FIRST_SESSION[1],
            ),
            JURY_CHAIR_A,
        ),
        201,
    )
    assert booked["status"] == "BOOKED"
    assert fixtures.read_jury_round(jury_round["id"])["version"] == read_once + 1

    # The second booking is legal on the merits — a different, non-overlapping
    # juror — and fails only on the version the chair still holds.
    stale = api.create_juror_assignment(
        jury_round["id"],
        create_assignment_payload(
            second_juror["id"], read_once,
            session_start_at=SECOND_SESSION[0],
            session_end_at=SECOND_SESSION[1],
        ),
        JURY_CHAIR_A,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    after_refusal = fixtures.read_jury_round(jury_round["id"])
    assert after_refusal["version"] == read_once + 1, "nothing was written"
    assert fixtures.read_juror(first_juror["id"])["assignment_count"] == 1
    assert fixtures.read_juror(second_juror["id"])["assignment_count"] == 0

    retried = validate_success(
        api.create_juror_assignment(
            jury_round["id"],
            create_assignment_payload(
                second_juror["id"], after_refusal["version"],
                session_start_at=SECOND_SESSION[0],
                session_end_at=SECOND_SESSION[1],
            ),
            JURY_CHAIR_A,
        ),
        201,
    )
    assert retried["status"] == "BOOKED"
    assert retried["juror_id"] == second_juror["id"]

    settled = fixtures.read_jury_round(jury_round["id"])
    assert settled["version"] == read_once + 2
    assert fixtures.read_juror(first_juror["id"])["assignment_count"] == 1
    assert fixtures.read_juror(second_juror["id"])["assignment_count"] == 1


# ─── A wall's occupancy ────────────────────────────────

def test_a_clear_span_is_still_refused_when_the_wall_read_is_stale(api):
    """PRD §2.7: "Reserving a wall span for an artwork requires
    `expected_wall_segment_version`, matching the current `version` of the
    `WallSegment` named in the request. Another planner may have reserved
    centimetres on that wall since the acting registrar last read it — a
    non-colliding span always succeeds — so a stale quote means the planner's
    picture of `occupied_cm`, `available_cm` and `loaded_weight_kg` no longer
    describes the wall."

    PRD §3.7: "The span must clear its neighbours by a **15-centimetre hanging
    buffer**: the plan is refused with `ERR_WALL_SPAN_CONFLICT` if, for any other
    artwork on the same wall whose `placement_status` is `PLANNED` or `INSTALLED`,
    the requested `span_start_cm` less 15 is smaller than that neighbour's
    `span_end_cm` while at the same time the requested `span_end_cm` plus 15 is
    greater than that neighbour's `span_start_cm`."

    PRD §3.7: "A successful plan carries the work `UNPLACED → PLANNED`, stores its
    `wall_segment_id`, `span_start_cm` and `span_end_cm`, and recomputes the
    wall's three derived figures: `occupied_cm` as the sum of span widths over the
    artworks assigned to that wall whose `placement_status` is `PLANNED` or
    `INSTALLED`, `available_cm` as the wall's `length_cm` minus `occupied_cm`, and
    `loaded_weight_kg` as the sum of `weight_kg` over the same set."

    Design: Corner/cross_cutting_layers/occ_installation_plan_stale_wall_segment_version_rejected
    """
    ctx = fixtures.setup_installation_show(works=TWO_WORKS)
    wall_id = ctx["wall"]["id"]
    first, second = ctx["artworks"][0]["id"], ctx["artworks"][1]["id"]
    for artwork_id in (first, second):
        fixtures.file_condition_report(artwork_id, "INTAKE", "A")

    read_once = fixtures.read_wall(wall_id)["version"]

    planned = validate_success(
        api.file_installation_plan(
            first,
            create_installation_plan_payload(wall_id, *FIRST_SPAN, read_once),
            REGISTRAR,
        )
    )
    assert planned["placement_status"] == "PLANNED"

    loaded = fixtures.read_wall(wall_id)
    assert loaded["occupied_cm"] == 100.0
    assert loaded["loaded_weight_kg"] == FIRST_WORK_WEIGHT_KG
    assert loaded["version"] == read_once + 1

    # 300–400 cm clears the neighbour's right edge by 200 cm, far more than the
    # 15-centimetre buffer, so only the stale read can refuse it.
    assert SECOND_SPAN[0] - 15 > FIRST_SPAN[1]
    stale = api.file_installation_plan(
        second,
        create_installation_plan_payload(wall_id, *SECOND_SPAN, read_once),
        REGISTRAR,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    unplaced = fixtures.read_artwork(second)
    assert unplaced["placement_status"] == "UNPLACED"
    assert unplaced["wall_segment_id"] is None

    unchanged = fixtures.read_wall(wall_id)
    assert unchanged["occupied_cm"] == 100.0
    assert unchanged["loaded_weight_kg"] == FIRST_WORK_WEIGHT_KG
    assert unchanged["version"] == read_once + 1

    retried = validate_success(
        api.file_installation_plan(
            second,
            create_installation_plan_payload(
                wall_id, *SECOND_SPAN, unchanged["version"]
            ),
            REGISTRAR,
        )
    )
    assert retried["placement_status"] == "PLANNED"
    assert retried["span_start_cm"] == SECOND_SPAN[0]
    assert retried["span_end_cm"] == SECOND_SPAN[1]

    settled = fixtures.read_wall(wall_id)
    assert settled["occupied_cm"] == 200.0
    assert settled["available_cm"] == WALL_LENGTH_CM - 200.0
    assert settled["loaded_weight_kg"] == pytest.approx(
        FIRST_WORK_WEIGHT_KG + SECOND_WORK_WEIGHT_KG, abs=0.01
    )


# ─── The award budget ──────────────────────────────────

def test_the_second_confirmation_is_refused_before_its_budget_test_runs(api):
    """PRD §2.7: "Confirming an award requires `expected_exhibition_version`,
    matching the `Exhibition`'s current `version`. Confirming a different award
    legitimately consumes part of `award_budget_cents`, so a stale quote means the
    budget check would be computed against an out-of-date
    `award_committed_cents`."

    PRD §3.8: "Two budget tests then apply, each to its own kind of award: for an
    award with no sponsor, the exhibition's `award_committed_cents` plus this
    award's `prize_cents` must be at most `award_budget_cents`, else
    `ERR_AWARD_BUDGET_EXCEEDED`; and for a `PURCHASE_AWARD`, the sponsor's
    `purchase_award_committed_cents` plus this award's `prize_cents` must be at
    most that sponsor's `purchase_award_budget_cents`, else
    `ERR_SPONSOR_BUDGET_EXCEEDED`."

    PRD §2.10: "**Concurrency** — the `expected_…_version` field equals the
    parent's current `version`, else `ERR_STALE_VERSION` (412), over the six
    operations of §2.7."

    Design: Corner/cross_cutting_layers/occ_award_confirm_stale_exhibition_version_rejected
    """
    ctx = fixtures.setup_results_published_show(
        works=TWO_WORKS,
        exhibition_overrides={"award_budget_cents": COUNCIL_AWARD_BUDGET_CENTS},
    )
    exhibition_id = ctx["exhibition"]["id"]
    first_work, second_work = ctx["artworks"][0]["id"], ctx["artworks"][1]["id"]

    first_award = fixtures.propose_award(
        exhibition_id, first_work, "BEST_IN_SHOW", HALF_BUDGET_PRIZE_CENTS,
        headers=JURY_CHAIR_A,
    )
    second_award = fixtures.propose_award(
        exhibition_id, second_work, "JURORS_CHOICE", HALF_BUDGET_PRIZE_CENTS,
        headers=JURY_CHAIR_A,
    )

    read_once = fixtures.read_exhibition(exhibition_id)["version"]

    confirmed = validate_success(
        api.confirm_award(
            first_award["id"], {"expected_exhibition_version": read_once},
            JURY_CHAIR_B,
        )
    )
    assert confirmed["status"] == "CONFIRMED"

    committed = fixtures.read_exhibition(exhibition_id)
    assert committed["award_committed_cents"] == HALF_BUDGET_PRIZE_CENTS
    assert committed["version"] == read_once + 1

    # Two prizes of 200000 fit inside a 500000 budget, so the budget test would
    # have passed; the refusal is the version alone.
    assert 2 * HALF_BUDGET_PRIZE_CENTS <= COUNCIL_AWARD_BUDGET_CENTS
    stale = api.confirm_award(
        second_award["id"], {"expected_exhibition_version": read_once},
        JURY_CHAIR_B,
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert fixtures.read_award(second_award["id"])["status"] == "PROPOSED"
    after_refusal = fixtures.read_exhibition(exhibition_id)
    assert after_refusal["award_committed_cents"] == HALF_BUDGET_PRIZE_CENTS
    assert after_refusal["version"] == read_once + 1

    retried = validate_success(
        api.confirm_award(
            second_award["id"],
            {"expected_exhibition_version": after_refusal["version"]},
            JURY_CHAIR_B,
        )
    )
    assert retried["status"] == "CONFIRMED"
    assert fixtures.read_exhibition(exhibition_id)["award_committed_cents"] == (
        2 * HALF_BUDGET_PRIZE_CENTS
    )


# ─── The acceptance capacity ───────────────────────────

def test_the_second_promotion_is_refused_though_seats_remain(api):
    """PRD §2.7: "Promoting a waitlisted artwork requires
    `expected_exhibition_version`. Promoting a different waitlisted work
    legitimately raises `accepted_count`, so a stale quote means the promoter is
    deciding against a capacity figure the exhibition no longer has."

    PRD §3.6: "A per-medium cap keeps one category from taking the whole show: the
    cap is the exhibition's `acceptance_capacity` multiplied by 0.40 and rounded
    **up** to a whole number, so a capacity of 3 permits 2 works per medium."

    PRD §3.6: "Promotion requires that `accepted_count` be strictly below
    `acceptance_capacity`, else `ERR_ACCEPTANCE_CAPACITY_REACHED`, and requires
    `expected_exhibition_version` to match."

    PRD §3.6: "A successful promotion raises `accepted_count` by one and lowers
    `waitlisted_count` by one, and increments both the exhibition's `version` and
    the artwork's `version` by 1."

    Design: Corner/cross_cutting_layers/occ_promotion_stale_exhibition_version_rejected
    """
    ctx = fixtures.setup_results_published_show(
        works=FOUR_PAINTINGS,
        scores=FOUR_CARDS,
        exhibition_overrides=dict(WIDE_CAPACITY),
    )
    exhibition_id = ctx["exhibition"]["id"]
    ranked_ids = [artwork["id"] for artwork in ctx["artworks"]]
    result = ctx["acceptance_result"]

    for artwork_id, expected_mean in zip(ranked_ids, FOUR_CERTIFIED_MEANS):
        assert fixtures.read_artwork(artwork_id)["certified_mean_score"] == (
            pytest.approx(expected_mean, abs=0.01)
        )

    assert result["accepted_artwork_ids"] == ranked_ids[:MEDIUM_CAP]
    assert result["waitlisted_artwork_ids"] == ranked_ids[MEDIUM_CAP:]
    assert result["accepted_count"] == MEDIUM_CAP
    assert result["waitlisted_count"] == 2
    assert result["declined_count"] == 0

    third, fourth = ranked_ids[2], ranked_ids[3]
    read_once = fixtures.read_exhibition(exhibition_id)["version"]

    promoted = validate_success(
        api.promote_artwork(
            third, {"expected_exhibition_version": read_once}, JURY_CHAIR_A
        )
    )
    assert promoted["status"] == "ACCEPTED"

    partway = fixtures.read_exhibition(exhibition_id)
    assert partway["accepted_count"] == 3
    assert partway["waitlisted_count"] == 1
    assert partway["version"] == read_once + 1

    # Three accepted is still below the capacity of five, so the capacity test
    # would have passed for the fourth work too.
    assert partway["accepted_count"] < partway["acceptance_capacity"]
    stale = api.promote_artwork(
        fourth, {"expected_exhibition_version": read_once}, JURY_CHAIR_A
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert fixtures.read_artwork(fourth)["status"] == "WAITLISTED"
    after_refusal = fixtures.read_exhibition(exhibition_id)
    assert after_refusal["accepted_count"] == 3
    assert after_refusal["waitlisted_count"] == 1
    assert after_refusal["version"] == read_once + 1

    retried = validate_success(
        api.promote_artwork(
            fourth, {"expected_exhibition_version": after_refusal["version"]},
            JURY_CHAIR_A,
        )
    )
    assert retried["status"] == "ACCEPTED"

    settled = fixtures.read_exhibition(exhibition_id)
    assert settled["accepted_count"] == 4
    assert settled["waitlisted_count"] == 0


# ─── The settlement ledger ─────────────────────────────

def test_the_second_payout_is_refused_and_blocks_the_settlement_advance(api):
    """PRD §2.7: "Releasing an artist payout requires
    `expected_exhibition_version`. Releasing the payout of a different sale
    legitimately raises `payouts_released_cents`, so a stale quote means the
    releasing officer's view of the settlement ledger is out of date."

    PRD §3.9: "On success the sale records `payout_released_by_user_id`, the
    exhibition's `payouts_released_cents` — the sum of `artist_payable_cents` over
    that exhibition's sales at `PAYOUT_RELEASED` — is recomputed, and both the
    exhibition's `version` and the sale's `version` increment by 1."

    PRD §3.10: "Advancing to `PAYOUTS_RELEASED` requires that no sale of the
    exhibition still sit at `RECORDED` or `INVOICED` — every non-voided sale must
    have reached `PAID` or `PAYOUT_RELEASED` — and that `payouts_released_cents`
    equal `artist_payable_total_cents` exactly, else `ERR_PAYOUT_INCOMPLETE`."

    Design: Corner/cross_cutting_layers/occ_payout_release_stale_exhibition_version_rejected
    """
    ctx = fixtures.setup_on_view_show(works=TWO_WORKS)
    exhibition_id = ctx["exhibition"]["id"]
    first_work, second_work = ctx["accepted_artwork_ids"]

    first_sale = fixtures.setup_paid_sale(
        first_work, recorder=FINANCE_A, sale_price_cents=SALE_PRICE_CENTS
    )
    second_sale = fixtures.setup_paid_sale(
        second_work, recorder=FINANCE_A, sale_price_cents=SALE_PRICE_CENTS,
        buyer_name="L. Moreau",
    )
    for sale in (first_sale, second_sale):
        assert sale["status"] == "PAID"
        assert sale["artist_payable_cents"] == ARTIST_PAYABLE_CENTS

    fixtures.advance_settlement(exhibition_id, "RECONCILING", FINANCE_B)
    reconciling = fixtures.read_exhibition(exhibition_id)
    assert reconciling["artist_payable_total_cents"] == TWO_PAYABLES_CENTS
    read_once = reconciling["version"]

    released = validate_success(
        api.release_sale_payout(
            first_sale["id"], {"expected_exhibition_version": read_once},
            FINANCE_B,
        )
    )
    assert released["status"] == "PAYOUT_RELEASED"

    partway = fixtures.read_exhibition(exhibition_id)
    assert partway["payouts_released_cents"] == ARTIST_PAYABLE_CENTS
    assert partway["version"] == read_once + 1

    stale = api.release_sale_payout(
        second_sale["id"], {"expected_exhibition_version": read_once}, FINANCE_B
    )
    validate_error(stale, ApiErrorId.ERR_STALE_VERSION.value, 412)

    assert fixtures.read_sale(second_sale["id"])["status"] == "PAID"
    after_refusal = fixtures.read_exhibition(exhibition_id)
    assert after_refusal["payouts_released_cents"] == ARTIST_PAYABLE_CENTS
    assert after_refusal["version"] == read_once + 1

    # The ledger is genuinely short, not merely reported short, so the
    # settlement advance is refused while the second payout is outstanding.
    blocked = api.advance_settlement(
        exhibition_id, {"target_settlement_status": "PAYOUTS_RELEASED"},
        FINANCE_B,
    )
    validate_error(blocked, ApiErrorId.ERR_PAYOUT_INCOMPLETE.value, 409)

    retried = validate_success(
        api.release_sale_payout(
            second_sale["id"],
            {"expected_exhibition_version": after_refusal["version"]},
            FINANCE_B,
        )
    )
    assert retried["status"] == "PAYOUT_RELEASED"

    settled = fixtures.read_exhibition(exhibition_id)
    assert settled["payouts_released_cents"] == TWO_PAYABLES_CENTS
    assert settled["payouts_released_cents"] == (
        settled["artist_payable_total_cents"]
    )

    advanced = validate_success(
        api.advance_settlement(
            exhibition_id, {"target_settlement_status": "PAYOUTS_RELEASED"},
            FINANCE_B,
        )
    )
    assert advanced["settlement_status"] == "PAYOUTS_RELEASED"
