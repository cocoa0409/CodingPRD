"""Actions and their exact compensating actions (PRD §2.9, §3.5, §3.9).

Two ledgers that must land back on their pre-action values with no residue.  An
escort crew's booked minutes are recomputed from the surviving reserved rows, so
a reserve-then-release cycle returns the crew to exactly zero and a second
identical cycle does so again — an implementation that decrements by a
re-derived duration drifts.  A claim reversal is the wider case: one call must
unwind three charge fields, three party balances, two party statuses, the leg
hold and the order's posture together.
"""

from test_helpers import (
    TEST_USERS,
    api_client,
    adjudicate_damage_claim,
    assert_allocation_sums_exactly,
    assert_network_chargeback_conserved,
    create_escort_assignment_payload,
    make_transport_manager_headers,
    read_damage_claim,
    read_escort_assignment,
    read_escort_crew,
    read_hauler,
    read_order,
    read_order_summary,
    read_plant,
    read_route_leg,
    read_set_crew,
    release_escort,
    reverse_damage_claim,
    setup_leg_awaiting_escorts,
    setup_scheduled_leg_for_claim,
    validate_success,
)

ADMIN = TEST_USERS["network_admin_headers"]

CYCLE_WINDOW_START = "2026-08-03T06:00:00.000Z"
CYCLE_WINDOW_END = "2026-08-03T14:00:00.000Z"


def _leg_with_a_tight_ceiling_crew():
    """One leg spanning 06:00Z-18:00Z and one crew whose ceiling is 300 minutes.

    The crew carries no turnaround buffer, so the same 06:00Z-14:00Z window can
    be booked again after the first booking is released, and its 300-minute
    ceiling means each 480-minute booking flips it to `OVERBOOKED`.
    """
    scenario = setup_leg_awaiting_escorts(
        escort_crews=[
            {
                "vendor_name": "Cycle Escort",
                "endorsement_class": "STANDARD",
                "buffer_minutes": 0,
                "max_reserved_minutes": 300,
            }
        ],
    )
    scenario["escort_crew"] = scenario["escort_crews"][0]
    return scenario


def _reserve_the_morning_window(scenario):
    """Book 06:00Z-14:00Z as the carrier that owns the leg; expects HTTP 201."""
    return validate_success(
        api_client.create_escort_assignment(
            create_escort_assignment_payload(
                scenario["leg"]["id"],
                scenario["escort_crew"]["id"],
                role="ESCORT",
                window_start=CYCLE_WINDOW_START,
                window_end=CYCLE_WINDOW_END,
            ),
            make_transport_manager_headers(scenario["hauler"]["id"]),
        ),
        201,
    )


def test_two_reserve_release_cycles_each_return_the_crew_ledger_to_zero():
    """PRD §2.9: "The **escort reserved-minute ledger** is conserved per crew: a
    crew's `reserved_minutes` always equals the sum of the frozen `reserved_minutes`
    of its currently reserved assignments, so a reservation followed by its
    compensating release returns the crew to its exact prior figure with zero drift."
    PRD §3.5: "Release is the exact compensating action for creation: the crew's
    booked minutes must return to their precise pre-reservation value."
    PRD §3.5: "After every recomputation the crew's `status` is refreshed:
    `OVERBOOKED` when the total exceeds `max_reserved_minutes`, `AVAILABLE`
    otherwise."

    Design: Difficulty/compensating_invariant/escort_reserved_minutes_restored_to_zero_after_release
    """
    scenario = _leg_with_a_tight_ceiling_crew()
    crew_id = scenario["escort_crew"]["id"]

    opening = read_escort_crew(crew_id)
    assert opening["reserved_minutes"] == 0, (
        f"a new crew opens with no booked minutes, got {opening['reserved_minutes']}"
    )

    for cycle in (1, 2):
        assignment = _reserve_the_morning_window(scenario)

        booked = read_escort_crew(crew_id)
        assert booked["reserved_minutes"] == 480, (
            f"cycle {cycle}: the eight-hour window books 480 minutes, got "
            f"{booked['reserved_minutes']}"
        )
        assert booked["status"] == "OVERBOOKED", (
            f"cycle {cycle}: 480 minutes exceed the 300-minute ceiling, got "
            f"{booked['status']}"
        )

        release_escort(assignment["id"], scenario["hauler"]["id"])

        restored = read_escort_crew(crew_id)
        assert restored["reserved_minutes"] == 0, (
            f"cycle {cycle}: no reserved row survives, so the ledger recomputes to 0, "
            f"got {restored['reserved_minutes']}"
        )
        assert restored["status"] == "AVAILABLE", (
            f"cycle {cycle}: an empty ledger is within the ceiling, got "
            f"{restored['status']}"
        )


def test_released_assignments_keep_their_frozen_minutes_after_both_cycles():
    """PRD §3.5: "A reservation's own `reserved_minutes` is computed once, at
    creation, as the number of minutes between `window_start` and `window_end` — the
    elapsed seconds divided by sixty, rounded half up to a whole minute — and is
    frozen from then on."
    PRD §3.5: "A crew's `reserved_minutes` is never incremented; it is recomputed in
    full as the sum of the frozen `reserved_minutes` of every one of that crew's
    reservations currently in `RESERVED` status."
    PRD §3.5: "Released and completed reservations contribute nothing."

    Design: Difficulty/compensating_invariant/escort_reserved_minutes_restored_to_zero_after_release
    """
    scenario = _leg_with_a_tight_ceiling_crew()

    first = _reserve_the_morning_window(scenario)
    release_escort(first["id"], scenario["hauler"]["id"])
    second = _reserve_the_morning_window(scenario)
    release_escort(second["id"], scenario["hauler"]["id"])

    for label, assignment_id in (("first", first["id"]), ("second", second["id"])):
        row = read_escort_assignment(assignment_id)
        assert row["status"] == "RELEASED", (
            f"the {label} reservation was released, got {row['status']}"
        )
        assert row["reserved_minutes"] == 480, (
            f"the {label} reservation keeps its frozen 480 minutes — release zeroes "
            f"the crew rollup, not the row, got {row['reserved_minutes']}"
        )

    crew = read_escort_crew(scenario["escort_crew"]["id"])
    assert crew["reserved_minutes"] == 0, (
        "two frozen 480-minute rows that are both RELEASED contribute nothing, got "
        f"{crew['reserved_minutes']}"
    )
    assert crew["status"] == "AVAILABLE", (
        f"an empty ledger leaves the crew AVAILABLE, got {crew['status']}"
    )


def _adjudicated_capped_claim_split_between_plant_and_hauler():
    """A ceiling-sized claim adjudicated on the evidence basis.

    The claim is opened at exactly the 2,500,000-cent single-claim ceiling with one
    evidence point against the plant, one against the hauler and none against the
    installer, so the ten percent haircut leaves 2,250,000 to split down the middle.
    Both halves clear their party thresholds, so the hauler is suspended, its
    `SCHEDULED` leg is held and the order is blocked.
    """
    scenario = setup_scheduled_leg_for_claim(
        claimed_amount_cents=2500000,
        discovered_stage="IN_TRANSIT",
        claim_overrides={
            "blocks_set": False,
            "plant_evidence_points": 1,
            "hauler_evidence_points": 1,
            "installer_evidence_points": 0,
        },
    )
    scenario["claim"] = adjudicate_damage_claim(
        scenario["claim"]["id"], allocation_basis="EVIDENCE"
    )
    return scenario


def test_reversal_zeroes_every_charge_and_restores_both_party_ledgers():
    """PRD §3.9: "Whichever basis is chosen, the approved amount is computed the same
    way: the claimed amount less a ten percent approval haircut — that is, ninety
    percent of `claimed_amount_cents`, rounded half up to whole cents — and stored as
    `approved_amount_cents`."
    PRD §3.9: "Third, threshold refresh on inclusive bounds: a hauler whose balance
    has reached five thousand dollars moves `ACTIVE → SUSPENDED`, and a plant whose
    balance has reached seven thousand five hundred dollars moves to `PROBATION`."
    PRD §3.9: "The three charge fields are zeroed, `allocation_basis` and
    `approved_amount_cents` are cleared back to null, and every party's
    `chargeback_balance_cents` is recomputed in full — dropping the reversed claim
    from every sum, which decreases each balance by exactly what the adjudication had
    added and restores the conserved network chargeback total of §2.9."
    PRD §2.9: "The **network chargeback total** — the sum of every plant's, every
    hauler's and every set crew's `chargeback_balance_cents` — always equals the sum
    of `approved_amount_cents` over all adjudicated damage claims; reversing a claim
    therefore restores the total precisely, with no residue."

    Design: Difficulty/compensating_invariant/chargeback_ledger_and_holds_restored_after_claim_reversal
    """
    scenario = _adjudicated_capped_claim_split_between_plant_and_hauler()
    claim_id = scenario["claim"]["id"]

    settled = read_damage_claim(claim_id)
    assert settled["status"] == "ADJUDICATED", (
        f"the claim was settled before the reversal, got {settled['status']}"
    )
    assert settled["approved_amount_cents"] == 2250000, (
        "ninety percent of the 2,500,000-cent ceiling is 2,250,000, got "
        f"{settled['approved_amount_cents']}"
    )
    assert settled["plant_charge_cents"] == 1125000, (
        f"a one-to-one evidence split charges the plant 1,125,000, got "
        f"{settled['plant_charge_cents']}"
    )
    assert settled["hauler_charge_cents"] == 1125000, (
        f"a one-to-one evidence split charges the hauler 1,125,000, got "
        f"{settled['hauler_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 0, (
        "the installer scored no evidence points, so it is charged nothing, got "
        f"{settled['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(settled)

    plant = read_plant(scenario["plant"]["id"])
    assert plant["chargeback_balance_cents"] == 1125000, (
        f"the plant's balance is its single charge, got {plant['chargeback_balance_cents']}"
    )
    assert plant["status"] == "PROBATION", (
        "1,125,000 cents has reached the 750,000-cent probation bound, got "
        f"{plant['status']}"
    )
    hauler = read_hauler(scenario["hauler"]["id"])
    assert hauler["chargeback_balance_cents"] == 1125000, (
        f"the hauler's balance is its single charge, got {hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "SUSPENDED", (
        "1,125,000 cents has reached the 500,000-cent suspension bound, got "
        f"{hauler['status']}"
    )
    crew = read_set_crew(scenario["set_crew"]["id"])
    assert crew["chargeback_balance_cents"] == 0, (
        f"the installer was charged nothing, got {crew['chargeback_balance_cents']}"
    )
    assert_network_chargeback_conserved(
        read_order_summary(scenario["order"]["id"]), 2250000
    )

    reversed_claim = reverse_damage_claim(claim_id)
    assert reversed_claim["status"] == "REVERSED", (
        f"the reversal moves the claim to REVERSED, got {reversed_claim['status']}"
    )

    after = read_damage_claim(claim_id)
    for field in (
        "plant_charge_cents",
        "hauler_charge_cents",
        "installer_charge_cents",
    ):
        assert after[field] == 0, f"{field} is zeroed by the reversal, got {after[field]}"
    assert after["approved_amount_cents"] is None, (
        f"approved_amount_cents is cleared back to null, got {after['approved_amount_cents']}"
    )
    assert after["allocation_basis"] is None, (
        f"allocation_basis is cleared back to null, got {after['allocation_basis']}"
    )

    plant = read_plant(scenario["plant"]["id"])
    assert plant["chargeback_balance_cents"] == 0, (
        "a reversed claim contributes nothing to the plant's sum, got "
        f"{plant['chargeback_balance_cents']}"
    )
    assert plant["status"] == "ACTIVE", (
        f"a plant back below the probation bound returns to ACTIVE, got {plant['status']}"
    )
    hauler = read_hauler(scenario["hauler"]["id"])
    assert hauler["chargeback_balance_cents"] == 0, (
        "a reversed claim contributes nothing to the hauler's sum, got "
        f"{hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "ACTIVE", (
        f"a hauler back below the suspension bound returns to ACTIVE, got {hauler['status']}"
    )
    crew = read_set_crew(scenario["set_crew"]["id"])
    assert crew["chargeback_balance_cents"] == 0, (
        f"the installer's balance never moved, got {crew['chargeback_balance_cents']}"
    )
    assert_network_chargeback_conserved(
        read_order_summary(scenario["order"]["id"]), 0
    )


def test_reversal_releases_the_hauler_hold_and_unblocks_the_order():
    """PRD §3.9: "Fourth, because a hauler was suspended, every route leg of that
    hauler whose `status` is `SCHEDULED` moves `SCHEDULED → HAULER_HOLD`."
    PRD §3.9: "Fifth, because a leg entered `HAULER_HOLD`, the posture of every order
    behind such a leg is re-derived and lands on `TRANSPORT_BLOCKED`."
    PRD §3.9: "`Plant.status`, `Hauler.status` and `SetCrew.status` are refreshed: a
    hauler whose balance has fallen below five thousand dollars returns to `ACTIVE`, a
    plant whose balance has fallen below seven thousand five hundred dollars returns
    to `ACTIVE`, and every leg of a restored hauler sitting in `HAULER_HOLD` moves
    `HAULER_HOLD → SCHEDULED`."
    PRD §2.8: "Otherwise the posture is `OPEN`. A freshly created order with no
    descendants at all therefore reads `OPEN`."

    Design: Difficulty/compensating_invariant/chargeback_ledger_and_holds_restored_after_claim_reversal
    """
    scenario = _adjudicated_capped_claim_split_between_plant_and_hauler()

    held_leg = read_route_leg(scenario["leg"]["id"])
    assert held_leg["status"] == "HAULER_HOLD", (
        "the suspension drove the carrier's scheduled leg into HAULER_HOLD, got "
        f"{held_leg['status']}"
    )
    blocked_order = read_order(scenario["order"]["id"])
    assert blocked_order["posture"] == "TRANSPORT_BLOCKED", (
        "a leg in HAULER_HOLD blocks the order at band two, got "
        f"{blocked_order['posture']}"
    )

    reverse_damage_claim(scenario["claim"]["id"])

    restored_leg = read_route_leg(scenario["leg"]["id"])
    assert restored_leg["status"] == "SCHEDULED", (
        "the restored carrier's held leg returns to SCHEDULED, got "
        f"{restored_leg['status']}"
    )
    restored_order = read_order(scenario["order"]["id"])
    assert restored_order["posture"] == "OPEN", (
        "with no hold, no set job and no site the ladder falls through to OPEN, got "
        f"{restored_order['posture']}"
    )
    summary = read_order_summary(scenario["order"]["id"])
    assert summary["posture"] == "OPEN", (
        f"the roll-up reports the same posture as the order row, got {summary['posture']}"
    )
    assert summary["sections_on_hold_count"] == 0, (
        "the claim never blocked the set, so no floor was ever held, got "
        f"{summary['sections_on_hold_count']}"
    )
