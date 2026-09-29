"""Adjudicating a claim fans out along the money ledger (PRD §3.9).

One adjudicate call writes the allocation, recomputes the charged party's
chargeback balance, refreshes that party's status across the suspension
threshold, drives the carrier's scheduled legs into `HAULER_HOLD` and finally
re-derives the posture of every order behind such a leg.
"""

from test_helpers import (
    TEST_USERS,
    adjudicate_damage_claim_payload,
    api_client,
    assert_allocation_sums_exactly,
    read_hauler,
    read_order,
    read_plant,
    read_route_leg,
    read_set_crew,
    setup_scheduled_leg_for_claim,
    validate_success,
)


def _adjudicate_on_stage(claim_id):
    return validate_success(
        api_client.adjudicate_damage_claim(
            claim_id,
            adjudicate_damage_claim_payload("STAGE"),
            TEST_USERS["claims_adjuster_headers"],
        )
    )


def test_stage_adjudication_suspends_the_carrier_and_holds_its_scheduled_leg():
    """PRD §3.9: "Whichever basis is chosen, the approved amount is computed the
    same way: the claimed amount less a ten percent approval haircut — that is,
    ninety percent of `claimed_amount_cents`, rounded half up to whole cents — and
    stored as `approved_amount_cents`."
    PRD §3.9: "Damage found at `PLANT_QC` belongs to the plant, damage found
    `IN_TRANSIT` belongs to the hauler, and damage found either `AT_SET` or at
    `FINAL_INSPECTION` belongs to the installer."
    PRD §3.9: "Third, threshold refresh on inclusive bounds: a hauler whose balance
    has reached five thousand dollars moves `ACTIVE → SUSPENDED`, and a plant whose
    balance has reached seven thousand five hundred dollars moves to `PROBATION`."
    PRD §3.9: "Fourth, because a hauler was suspended, every route leg of that
    hauler whose `status` is `SCHEDULED` moves `SCHEDULED → HAULER_HOLD`."
    PRD §3.9: "Fifth, because a leg entered `HAULER_HOLD`, the posture of every
    order behind such a leg is re-derived and lands on `TRANSPORT_BLOCKED`."

    Design: Difficulty/transitive_cascade/claim_adjudicate_five_level_chargeback_cascade
    """
    scenario = setup_scheduled_leg_for_claim(
        claimed_amount_cents=611112,
        discovered_stage="IN_TRANSIT",
        claim_overrides={"blocks_set": False},
    )
    assert scenario["claim"]["status"] == "UNDER_REVIEW", (
        f"the claim must be UNDER_REVIEW before adjudication, got {scenario['claim']['status']}"
    )
    assert scenario["leg"]["status"] == "SCHEDULED", (
        f"the leg must still be SCHEDULED before the suspension, got {scenario['leg']['status']}"
    )
    assert scenario["hauler"]["status"] == "ACTIVE", (
        f"the carrier starts ACTIVE with a zero balance, got {scenario['hauler']['status']}"
    )

    adjudicated = _adjudicate_on_stage(scenario["claim"]["id"])

    assert adjudicated["status"] == "ADJUDICATED", (
        f"UNDER_REVIEW -> ADJUDICATED expected, got {adjudicated['status']}"
    )
    assert adjudicated["approved_amount_cents"] == 550001, (
        "ninety percent of 611112 cents rounded half up is 550001, got "
        f"{adjudicated['approved_amount_cents']}"
    )
    assert adjudicated["hauler_charge_cents"] == 550001, (
        "damage discovered IN_TRANSIT charges the whole approved amount to the "
        f"carrier, expected 550001, got {adjudicated['hauler_charge_cents']}"
    )
    assert_allocation_sums_exactly(adjudicated)

    hauler = read_hauler(scenario["hauler"]["id"])
    assert hauler["chargeback_balance_cents"] == 550001, (
        "the carrier's balance is the sum of hauler_charge_cents over its "
        f"adjudicated claims, expected 550001, got {hauler['chargeback_balance_cents']}"
    )
    assert hauler["status"] == "SUSPENDED", (
        "a balance at or above 500,000 cents suspends the carrier, got "
        f"{hauler['status']}"
    )

    leg = read_route_leg(scenario["leg"]["id"])
    assert leg["status"] == "HAULER_HOLD", (
        "the suspended carrier's SCHEDULED leg must move to HAULER_HOLD, got "
        f"{leg['status']}"
    )

    order = read_order(scenario["order"]["id"])
    assert order["posture"] == "TRANSPORT_BLOCKED", (
        "a leg in HAULER_HOLD drives the order behind it to TRANSPORT_BLOCKED, got "
        f"{order['posture']}"
    )


def test_stage_adjudication_leaves_the_unnamed_parties_ledgers_clean():
    """PRD §3.9: "Under the `STAGE` basis, the entire approved amount is charged to
    the single party that owns the stage at which the damage was discovered, and the
    other two charges stay at 0; evidence points are ignored completely."
    PRD §3.9: "Those balances are always recomputed in full, never adjusted: a
    plant's balance is the sum of `plant_charge_cents` over every claim in
    `ADJUDICATED` status whose order resolves to that plant; a hauler's balance is
    the sum of `hauler_charge_cents` over every claim in `ADJUDICATED` status naming
    that hauler; a set crew's balance is the sum of `installer_charge_cents` over
    every claim in `ADJUDICATED` status naming that crew."
    PRD §3.1: "A plant starts life with a `chargeback_balance_cents` of 0 and a
    `status` of `ACTIVE`; that balance is a computed running total of the plant's
    share of settled damage claims, and the plant flips to `PROBATION` once the
    balance reaches seven thousand five hundred dollars — that is, at or above
    750,000 cents — falling back to `ACTIVE` if a reversal drops it below that line."

    Design: Difficulty/transitive_cascade/claim_adjudicate_five_level_chargeback_cascade
    """
    scenario = setup_scheduled_leg_for_claim(
        claimed_amount_cents=611112,
        discovered_stage="IN_TRANSIT",
        claim_overrides={"blocks_set": False},
    )

    adjudicated = _adjudicate_on_stage(scenario["claim"]["id"])

    assert adjudicated["plant_charge_cents"] == 0, (
        "a transit-stage allocation charges the plant nothing, got "
        f"{adjudicated['plant_charge_cents']}"
    )
    assert adjudicated["installer_charge_cents"] == 0, (
        "a transit-stage allocation charges the installer nothing, got "
        f"{adjudicated['installer_charge_cents']}"
    )

    plant = read_plant(scenario["plant"]["id"])
    assert plant["chargeback_balance_cents"] == 0, (
        "the plant is charged nothing, so its recomputed balance stays 0, got "
        f"{plant['chargeback_balance_cents']}"
    )
    assert plant["status"] == "ACTIVE", (
        "a zero balance is far below the 750,000-cent probation line, so the plant "
        f"stays ACTIVE, got {plant['status']}"
    )

    set_crew = read_set_crew(scenario["set_crew"]["id"])
    assert set_crew["chargeback_balance_cents"] == 0, (
        "the installer is charged nothing, so its recomputed balance stays 0, got "
        f"{set_crew['chargeback_balance_cents']}"
    )
    assert set_crew["status"] == "ACTIVE", (
        f"the installer crew's licence is current, so it stays ACTIVE, got {set_crew['status']}"
    )
