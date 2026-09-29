"""Two populations, two answers: the provisional/final tier pair and the
snapshot/settlement accrual pair, computed side by side on one roster."""

from __future__ import annotations

from test_helpers import (
    HOLY_LAND_TIERS,
    TWO_TIER_PRICE_TIERS,
    assert_accrual_snapshot,
    assert_settlement_snapshot,
    close_sales,
    confirm_traveler,
    active_agreement,
    deposited_traveler,
    enrol_traveler,
    assign_room,
    fully_paid_traveler,
    open_departure,
    pay,
    read_agreement,
    read_traveler,
    settle_agreement,
)


def _two_tier_departure():
    """A departure whose P1 tier covers exactly one traveler and P2 covers 2..3."""
    return open_departure(
        program_overrides={"price_tiers": [dict(t) for t in TWO_TIER_PRICE_TIERS]},
        departure_overrides={"min_pax": 1, "max_pax": 3},
    )


def _diverging_roster():
    """One fully-paid confirmed traveler plus one merely deposited traveler."""
    stage = _two_tier_departure()
    departure_id = stage["departure"]["id"]

    anna = fully_paid_traveler(
        departure_id,
        deposit_cents=60_000,
        method="CHECK",
        full_name="Anna Kessler",
        date_of_birth="1980-05-05",
    )
    bruno = deposited_traveler(
        departure_id,
        deposit_cents=60_000,
        full_name="Bruno Costa",
        date_of_birth="1982-07-07",
    )
    closed = close_sales(departure_id)
    return stage, closed, anna, bruno


def test_closing_sales_freezes_a_narrower_final_tier_than_the_live_provisional_tier(api):
    """PRD §3.1: "The **final** variant counts only travelers whose
    `booking_status` is `CONFIRMED` **and** whose `payment_status` is
    `PAID_IN_FULL`, and it applies **no** floor of one. It writes
    `final_tier_code` and `final_per_pax_price_cents` and nothing else. It runs
    at exactly one moment: the closing of sales."

    Design: Difficulty/dual_variant_calc/departure_tier_provisional_vs_final_divergence
    """
    _stage, closed, _anna, _bruno = _diverging_roster()

    assert closed["status"] == "SALES_CLOSED"
    # Provisional counts DEPOSITED or CONFIRMED: two travelers, so tier P2.
    assert closed["provisional_tier_code"] == "P2"
    assert closed["provisional_per_pax_price_cents"] == 587_000
    # Final counts only the fully-paid confirmed traveler: one, so tier P1.
    assert closed["final_tier_code"] == "P1"
    assert closed["final_per_pax_price_cents"] == 620_000
    assert closed["final_per_pax_price_cents"] - closed["provisional_per_pax_price_cents"] == 33_000


def test_closing_sales_reprices_the_confirmed_traveler_and_leaves_the_deposited_one(api):
    """PRD §3.1: "Once those pass, closing sales writes `final_tier_code` and
    `final_per_pax_price_cents`, leaves the provisional fields untouched,
    rewrites every `CONFIRMED` traveler's `price_locked_cents` to the new
    `final_per_pax_price_cents` and recomputes each of their invoices, re-quotes
    each such traveler's still-`QUOTED` travel protection at the new invoice,
    recomputes the departure's `land_cost_total_cents`, sets
    `service_coverage_ok` to true only when every service booking on the
    departure has reached `CONFIRMED`, and increments the departure's
    `version`."

    Design: Difficulty/dual_variant_calc/departure_tier_provisional_vs_final_divergence
    """
    _stage, _closed, anna, bruno = _diverging_roster()

    anna_after = read_traveler(anna["id"])
    assert anna_after["price_locked_cents"] == 620_000
    # gross 620000 -> grant 31000 (500bp) -> net 589000 -> fee 20615 -> 609615.
    assert anna_after["invoice_total_cents"] == 609_615

    bruno_after = read_traveler(bruno["id"])
    assert bruno_after["booking_status"] == "DEPOSITED"


def _settled_leader_roster():
    """Four recruits, two of them confirmed and paid in full, then settlement."""
    stage = open_departure(
        program_overrides={"price_tiers": [dict(t) for t in HOLY_LAND_TIERS]},
        departure_overrides={"min_pax": 1, "max_pax": 40},
    )
    departure_id = stage["departure"]["id"]

    agreement = active_agreement(
        departure_id,
        leader_name="Fr. Alonso Reyes",
        leader_user_id="u-leader-alonso",
        free_travel_threshold=2,
        commission_mode="PER_PAX_CASH",
        commission_rate_cents_per_pax=6000,
        accrual_basis="TRAVELED",
    )

    recruits = []
    for full_name, date_of_birth in (
        ("Recruit One", "1975-01-10"),
        ("Recruit Two", "1978-02-11"),
        ("Recruit Three", "1981-03-12"),
        ("Recruit Four", "1984-04-13"),
    ):
        traveler = enrol_traveler(
            departure_id,
            full_name=full_name,
            date_of_birth=date_of_birth,
            recruited_by_agreement_id=agreement["id"],
        )
        assign_room(traveler["id"])
        pay(traveler["id"], 50_000, method="PARISH_TRANSFER")
        recruits.append(traveler)

    for traveler in recruits[:2]:
        confirm_traveler(traveler["id"])
        pay(traveler["id"], 527_168)

    closed = close_sales(departure_id)
    settled = settle_agreement(agreement["id"])
    return stage, closed, settled, recruits


def test_leader_settlement_values_a_narrower_population_than_the_live_snapshot(api):
    """PRD §3.4: "The **settlement** variant counts only travelers whose
    `booking_status` is `CONFIRMED` and whose `payment_status` is
    `PAID_IN_FULL`, and values seats at the departure's
    `final_per_pax_price_cents`; it writes `settled_recruited_count`,
    `settled_earned_free_seats` and `settled_commission_cents`, leaving the
    snapshot fields untouched so both figures stay observable."

    Design: Difficulty/dual_variant_calc/leader_accrual_snapshot_vs_settlement_divergence
    """
    _stage, _closed, settled, _recruits = _settled_leader_roster()

    assert settled["status"] == "SETTLED"
    # Snapshot population: all four recruits are DEPOSITED or CONFIRMED.
    assert_accrual_snapshot(settled, 4, 2, 24_000)
    # Settlement population: only the two fully-paid confirmed recruits.
    assert_settlement_snapshot(settled, 2, 1, 12_000)


def test_leader_settlement_reads_the_final_tier_the_closing_of_sales_wrote(api):
    """PRD §3.4: "Settlement is a `FinanceController` action that moves an
    `ACTIVE` agreement to `SETTLED`. It requires the agreement to be `ACTIVE`,
    failing which the answer is `ERR_AGREEMENT_INVALID_STATE`, and it requires
    the parent departure's status to be `SALES_CLOSED` or `OPERATED`, failing
    which the answer is `ERR_DEPARTURE_INVALID_STATE` — there is no traveled
    basis to settle against until the roster has closed."

    Design: Difficulty/dual_variant_calc/leader_accrual_snapshot_vs_settlement_divergence
    """
    _stage, closed, settled, recruits = _settled_leader_roster()

    assert closed["status"] == "SALES_CLOSED"
    # Two fully-paid confirmed travelers fall inside tier T1 (1..9).
    assert closed["final_tier_code"] == "T1"
    assert closed["final_per_pax_price_cents"] == 587_000

    first_recruit = read_traveler(recruits[0]["id"])
    # gross 587000 -> grant 29350 -> net 557650 -> fee 19518 -> 577168.
    assert first_recruit["invoice_total_cents"] == 577_168

    reread = read_agreement(settled["id"])
    assert reread["settled_commission_cents"] == 12_000
