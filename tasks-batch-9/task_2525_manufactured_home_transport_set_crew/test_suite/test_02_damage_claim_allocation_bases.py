"""Two allocation bases over byte-identical claim data.

A single `allocation_basis` choice decides whether the approved amount lands
whole on the party owning the discovery stage, or is split across all three
parties by floor-plus-largest-remainder. The approved amount itself — the
claimed amount less the ten percent approval haircut — is identical either way.
"""

from test_helpers import (
    TEST_USERS,
    adjudicate_damage_claim_payload,
    api_client,
    assert_allocation_sums_exactly,
    assert_damage_claim,
    open_damage_claim,
    read_hauler,
    read_plant,
    read_set_crew,
    review_damage_claim,
    setup_claim_under_review,
    validate_success,
)

ADJUSTER = TEST_USERS["claims_adjuster_headers"]

# Identical inputs for both bases: an amount whose ninety-percent haircut lands
# on an odd number of cents, a plant-QC discovery stage, and one evidence point
# apiece so every fractional remainder ties.
CLAIMED_AMOUNT_CENTS = 100001
EXPECTED_APPROVED_CENTS = 90001
EVIDENCE_POINTS = {
    "plant_evidence_points": 1,
    "hauler_evidence_points": 1,
    "installer_evidence_points": 1,
}


def _open_claim_under_review():
    """One plant, one carrier, one installer crew and a claim `UNDER_REVIEW`.

    The claim is opened for 100,001 cents at `PLANT_QC` with one evidence point
    scored against each party, and does not block the set.
    """
    return setup_claim_under_review(
        claimed_amount_cents=CLAIMED_AMOUNT_CENTS,
        discovered_stage="PLANT_QC",
        claim_overrides={"blocks_set": False, **EVIDENCE_POINTS},
    )


def _adjudicate(claim_id, allocation_basis):
    return validate_success(
        api_client.adjudicate_damage_claim(
            claim_id, adjudicate_damage_claim_payload(allocation_basis), ADJUSTER
        ),
        200,
    )


def test_stage_basis_charges_the_whole_approved_amount_to_the_stage_owner():
    """PRD §3.9: "Whichever basis is chosen, the approved amount is computed the
    same way: the claimed amount less a ten percent approval haircut — that is,
    ninety percent of `claimed_amount_cents`, rounded half up to whole cents —
    and stored as `approved_amount_cents`."
    PRD §3.9: "Under the `STAGE` basis, the entire approved amount is charged to
    the single party that owns the stage at which the damage was discovered, and
    the other two charges stay at 0; evidence points are ignored completely."
    PRD §3.9: "Damage found at `PLANT_QC` belongs to the plant, damage found
    `IN_TRANSIT` belongs to the hauler, and damage found either `AT_SET` or at
    `FINAL_INSPECTION` belongs to the installer."

    Design: Difficulty/dual_variant_calc/damage_claim_stage_vs_evidence_allocation
    """
    scenario = _open_claim_under_review()

    settled = _adjudicate(scenario["claim"]["id"], "STAGE")
    assert_damage_claim(settled)

    assert settled["status"] == "ADJUDICATED", (
        f"adjudication moves UNDER_REVIEW -> ADJUDICATED, got {settled['status']}"
    )
    assert settled["allocation_basis"] == "STAGE", (
        f"expected allocation_basis STAGE, got {settled['allocation_basis']}"
    )
    assert settled["approved_amount_cents"] == EXPECTED_APPROVED_CENTS, (
        "ninety percent of 100001 cents rounded half up is "
        f"{EXPECTED_APPROVED_CENTS}, got {settled['approved_amount_cents']}"
    )
    assert settled["plant_charge_cents"] == EXPECTED_APPROVED_CENTS, (
        "PLANT_QC belongs to the plant, so the whole approved amount is charged "
        f"there, got {settled['plant_charge_cents']}"
    )
    assert settled["hauler_charge_cents"] == 0, (
        f"the other two charges stay at 0, got {settled['hauler_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 0, (
        f"the other two charges stay at 0, got {settled['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(settled)


def test_evidence_basis_splits_the_approved_amount_by_largest_remainder():
    """PRD §3.9: "Each party is then provisionally charged the floor of its exact
    share, and the leftover — the approved amount less the sum of those three
    floors, which is always 0, 1 or 2 cents — is distributed one cent at a time
    to the parties ordered by the largest fractional part of their exact share
    first; ties on the fractional part are broken by the larger point score
    first; and ties on both are broken by the party's code in ascending
    alphabetical order, where the codes are the literal strings `HAULER`,
    `INSTALLER` and `PLANT` in that order."
    PRD §3.9: "Concretely, an approved amount of 90,001 cents split on points of
    one, one and one gives the plant 30,000, the hauler 30,001 and the installer
    30,000, rather than a single 90,001 charge."

    Design: Difficulty/dual_variant_calc/damage_claim_stage_vs_evidence_allocation
    """
    scenario = _open_claim_under_review()

    settled = _adjudicate(scenario["claim"]["id"], "EVIDENCE")
    assert_damage_claim(settled)

    assert settled["allocation_basis"] == "EVIDENCE", (
        f"expected allocation_basis EVIDENCE, got {settled['allocation_basis']}"
    )
    assert settled["approved_amount_cents"] == EXPECTED_APPROVED_CENTS, (
        "the haircut is basis-independent, so the approved amount is still "
        f"{EXPECTED_APPROVED_CENTS}, got {settled['approved_amount_cents']}"
    )
    assert settled["plant_charge_cents"] == 30000, (
        f"the plant takes the floor of its exact share, got {settled['plant_charge_cents']}"
    )
    assert settled["hauler_charge_cents"] == 30001, (
        "the single leftover cent goes to HAULER, first in ascending alphabetical "
        f"order once both prior tie-breaks tie, got {settled['hauler_charge_cents']}"
    )
    assert settled["installer_charge_cents"] == 30000, (
        "the installer takes the floor of its exact share, got "
        f"{settled['installer_charge_cents']}"
    )
    assert_allocation_sums_exactly(settled)

    plant = read_plant(scenario["plant"]["id"])
    hauler = read_hauler(scenario["hauler"]["id"])
    set_crew = read_set_crew(scenario["set_crew"]["id"])
    assert plant["chargeback_balance_cents"] == 30000, (
        "a plant's balance is the sum of plant_charge_cents over its adjudicated "
        f"claims, expected 30000, got {plant['chargeback_balance_cents']}"
    )
    assert hauler["chargeback_balance_cents"] == 30001, (
        "a hauler's balance is the sum of hauler_charge_cents over the claims "
        f"naming it, expected 30001, got {hauler['chargeback_balance_cents']}"
    )
    assert set_crew["chargeback_balance_cents"] == 30000, (
        "a set crew's balance is the sum of installer_charge_cents over the "
        f"claims naming it, expected 30000, got {set_crew['chargeback_balance_cents']}"
    )


def test_two_identical_claims_settled_on_different_bases_sum_into_one_ledger():
    """PRD §3.9: "Under the `EVIDENCE` basis, the same approved amount is split
    across all three parties in proportion to their evidence points, so identical
    claim data yields three non-zero charges instead of one."
    PRD §3.9: "Those balances are always recomputed in full, never adjusted: a
    plant's balance is the sum of `plant_charge_cents` over every claim in
    `ADJUDICATED` status whose order resolves to that plant; a hauler's balance is
    the sum of `hauler_charge_cents` over every claim in `ADJUDICATED` status
    naming that hauler; a set crew's balance is the sum of
    `installer_charge_cents` over every claim in `ADJUDICATED` status naming that
    crew."
    PRD §3.9: "Third, threshold refresh on inclusive bounds: a hauler whose
    balance has reached five thousand dollars moves `ACTIVE → SUSPENDED`, and a
    plant whose balance has reached seven thousand five hundred dollars moves to
    `PROBATION`."

    Design: Difficulty/dual_variant_calc/damage_claim_stage_vs_evidence_allocation
    """
    scenario = _open_claim_under_review()
    claim_a_id = scenario["claim"]["id"]

    claim_b = open_damage_claim(
        scenario["order"]["id"],
        scenario["section"]["id"],
        scenario["hauler"]["id"],
        scenario["set_crew"]["id"],
        discovered_stage="PLANT_QC",
        claimed_amount_cents=CLAIMED_AMOUNT_CENTS,
        blocks_set=False,
        **EVIDENCE_POINTS,
    )
    review_damage_claim(claim_b["id"])

    settled_a = _adjudicate(claim_a_id, "STAGE")
    settled_b = _adjudicate(claim_b["id"], "EVIDENCE")

    assert settled_a["approved_amount_cents"] == settled_b["approved_amount_cents"], (
        "the approval haircut is identical under both bases, got "
        f"{settled_a['approved_amount_cents']} and {settled_b['approved_amount_cents']}"
    )
    assert settled_a["plant_charge_cents"] == EXPECTED_APPROVED_CENTS, (
        f"the STAGE claim charges the plant alone, got {settled_a['plant_charge_cents']}"
    )
    assert (
        settled_b["plant_charge_cents"],
        settled_b["hauler_charge_cents"],
        settled_b["installer_charge_cents"],
    ) == (30000, 30001, 30000), (
        "the EVIDENCE claim yields three non-zero charges, got "
        f"{settled_b['plant_charge_cents']}/{settled_b['hauler_charge_cents']}/"
        f"{settled_b['installer_charge_cents']}"
    )

    plant = read_plant(scenario["plant"]["id"])
    hauler = read_hauler(scenario["hauler"]["id"])
    set_crew = read_set_crew(scenario["set_crew"]["id"])
    assert plant["chargeback_balance_cents"] == 120001, (
        "the plant carries 90001 from the STAGE claim plus 30000 from the "
        f"EVIDENCE claim, expected 120001, got {plant['chargeback_balance_cents']}"
    )
    assert hauler["chargeback_balance_cents"] == 30001, (
        "the hauler is charged only by the EVIDENCE claim, expected 30001, got "
        f"{hauler['chargeback_balance_cents']}"
    )
    assert set_crew["chargeback_balance_cents"] == 30000, (
        "the installer is charged only by the EVIDENCE claim, expected 30000, got "
        f"{set_crew['chargeback_balance_cents']}"
    )
    assert plant["status"] == "ACTIVE", (
        "120001 cents is below the 750000-cent probation line, so the plant "
        f"stays ACTIVE, got {plant['status']}"
    )
    assert hauler["status"] == "ACTIVE", (
        "30001 cents is below the 500000-cent suspension line, so the carrier "
        f"stays ACTIVE, got {hauler['status']}"
    )
