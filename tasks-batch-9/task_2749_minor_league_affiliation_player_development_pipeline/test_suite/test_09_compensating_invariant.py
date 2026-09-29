"""Quantities that must be conserved across a charge and its compensation:
a counted option year with a derived complement, and a monetary pool ledger.
"""

from test_helpers import (
    FARM_DIRECTOR_HEADERS,
    INTERNATIONAL_SCOUT_HEADERS,
    ApiClient,
    assert_integer,
    assert_money,
    assert_option_year_conservation,
    assert_pool_ledger_identity,
    assert_status,
    fixtures,
    validate_paginated,
)


# ---------------------------------------------------------------------------
# Instance 1 — three option years, conserved across two charges and a rescind
# ---------------------------------------------------------------------------


def _tides_club_with_two_pending_windows(api: ApiClient) -> dict:
    """One player holding two legally separated pending windows at one club."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Norfolk Tides",
            "level": "TRIPLE_A",
            "market_city": "Norfolk",
            "meal_stipend_cents_per_day": 3300,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    first = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Rowan Alcaraz",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2023-06-12",
            "service_days_accrued": 320,
        },
        effective_date="2026-04-01",
        end_date="2026-04-30",
    )
    second = fixtures.create_assignment(
        api,
        first["player_id"],
        club["affiliate_id"],
        movement_reason="LATERAL",
        effective_date="2026-05-03",
        end_date="2026-06-30",
    )
    club["player_id"] = first["player_id"]
    club["first_assignment_id"] = first["assignment_id"]
    club["second_assignment_id"] = second["id"]
    return club


def test_two_charging_activations_move_used_and_remaining_in_lockstep(api: ApiClient):
    """Each 20-day-plus activation spends one of the player's three years.

    PRD 3.6: "A player has three option years in total, so `option_years_used`
    is the number of `CHARGED` option-year records belonging to that player's
    assignments, and `option_years_remaining` is three minus that count, floored
    at zero — the two always sum to three, because rescinded records are
    excluded from the used count and the remainder is derived rather than
    independently decremented."  Both windows exceed the twenty-day threshold
    that PRD 3.6 attaches to the charge — "When the assignment is `LEVEL` or
    `COMPLEX` and its `projected_optional_days` is 20 or more, the server charges
    an option year" — so the pair walks 0/3 to 1/2 to 2/1.

    Design: Difficulty/compensating_invariant/option_year_count_conserved_across_two_charges_and_one_revoke
    """
    club = _tides_club_with_two_pending_windows(api)

    checkpoint_0 = fixtures.read_player(api, club["player_id"])
    assert_integer(checkpoint_0["option_years_used"], 0, "option_years_used")
    assert_integer(checkpoint_0["option_years_remaining"], 3, "option_years_remaining")
    assert_option_year_conservation(checkpoint_0)

    first = fixtures.dispose_assignment(api, club["first_assignment_id"], "ACTIVATE")
    assert first["option_year_charged"] is True, (
        f"a 30-day level window must charge an option year, got {first!r}"
    )
    checkpoint_1 = fixtures.read_player(api, club["player_id"])
    assert_integer(checkpoint_1["option_years_used"], 1, "option_years_used")
    assert_integer(checkpoint_1["option_years_remaining"], 2, "option_years_remaining")
    assert_option_year_conservation(checkpoint_1)

    second = fixtures.dispose_assignment(api, club["second_assignment_id"], "ACTIVATE")
    assert second["option_year_charged"] is True, (
        f"a 59-day level window must charge an option year, got {second!r}"
    )
    checkpoint_2 = fixtures.read_player(api, club["player_id"])
    assert_integer(checkpoint_2["option_years_used"], 2, "option_years_used")
    assert_integer(checkpoint_2["option_years_remaining"], 1, "option_years_remaining")
    assert_option_year_conservation(checkpoint_2)


def test_rescinding_one_charge_returns_the_year_while_retaining_the_record(api: ApiClient):
    """The compensation excludes a row from the count instead of deleting it.

    PRD 3.6: "From `ACTIVE`, revoking moves the row to `REVOKED` and unwinds
    everything the activation did: every option-year record whose
    `triggering_assignment_id` is this assignment and whose status is `CHARGED`
    moves to `RESCINDED`, which restores the player's `option_years_used` and
    `option_years_remaining`; the assignment's `option_year_charged` flips back
    to false".  The rescinded record keeps the `optional_days` it snapshotted, so
    the tally returns to 1/2 with both rows still listable and the untouched
    first assignment still holding its own roster slot.

    Design: Difficulty/compensating_invariant/option_year_count_conserved_across_two_charges_and_one_revoke
    """
    club = _tides_club_with_two_pending_windows(api)
    fixtures.dispose_assignment(api, club["first_assignment_id"], "ACTIVATE")
    fixtures.dispose_assignment(api, club["second_assignment_id"], "ACTIVATE")

    revoked = fixtures.dispose_assignment(
        api, club["second_assignment_id"], "REVOKE", note="second option rescinded"
    )
    assert_status(revoked, "REVOKED", "PlayerAssignment")
    assert revoked["option_year_charged"] is False, (
        f"revocation must flip option_year_charged back to false, got {revoked!r}"
    )

    checkpoint_3 = fixtures.read_player(api, club["player_id"])
    assert_integer(checkpoint_3["option_years_used"], 1, "option_years_used")
    assert_integer(checkpoint_3["option_years_remaining"], 2, "option_years_remaining")
    assert_option_year_conservation(checkpoint_3)

    second_rows, second_meta = validate_paginated(
        api.list_option_years(club["second_assignment_id"], FARM_DIRECTOR_HEADERS)
    )
    assert_integer(second_meta["total_count"], 1, "option-year total_count")
    assert_status(second_rows[0], "RESCINDED", "OptionYearRecord")
    assert_integer(second_rows[0]["optional_days"], 59, "optional_days")

    first_rows = fixtures.option_years_for(api, club["first_assignment_id"])
    assert len(first_rows) == 1, f"the first charge must retain one row, got {first_rows}"
    assert_status(first_rows[0], "CHARGED", "OptionYearRecord")
    assert_integer(first_rows[0]["optional_days"], 30, "optional_days")

    assert_status(
        fixtures.read_assignment(api, club["first_assignment_id"]),
        "ACTIVE",
        "PlayerAssignment",
    )
    affiliate = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(affiliate["active_roster_count"], 1, "active_roster_count")


# ---------------------------------------------------------------------------
# Instance 2 — the pool ledger balances across an approval and its void
# ---------------------------------------------------------------------------


def _academy_pool_with_two_submitted_signings(api: ApiClient) -> dict:
    """A clean 2026 pool carrying two submitted bonuses well inside it."""
    academy = fixtures.licensed_academy(
        api,
        affiliate_overrides={
            "name": "San Pedro Academy",
            "market_city": "San Pedro de Macoris",
            "meal_stipend_cents_per_day": 2500,
            "housing_beds": 40,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_3",
            "club_reimbursement_cap_cents": 100000,
            "minimum_active_players": 0,
        },
    )
    pool = fixtures.create_pool(
        api, season_year=2026, base_pool_cents=5000000, trade_adjustment_cents=0
    )
    first_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Wilkin Peralta",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    second_player = fixtures.create_player(
        api,
        INTERNATIONAL_SCOUT_HEADERS,
        full_name="Junior Almonte",
        origin="INTERNATIONAL_FA",
        signed_date="2026-01-15",
    )
    first_signing = fixtures.create_signing(
        api, pool["id"], first_player["id"], academy["affiliate_id"], bonus_cents=1200000
    )
    second_signing = fixtures.create_signing(
        api, pool["id"], second_player["id"], academy["affiliate_id"], bonus_cents=800000
    )
    return {
        "pool_id": pool["id"],
        "pool": pool,
        "first_signing_id": first_signing["id"],
        "second_signing_id": second_signing["id"],
    }


def test_each_approval_moves_allocated_and_remaining_by_the_same_bonus(api: ApiClient):
    """The two ledger halves always add back up to the effective pool.

    PRD 3.9: "`effective_pool_cents` is the base allotment plus the trade
    adjustment minus the forfeited amount, and `remaining_cents` is the effective
    pool minus the allocated amount."  PRD 3.9 also fixes what each approval
    contributes — "Once signings begin, `allocated_cents` is the sum of
    `pool_charge_cents` over the pool's `APPROVED` signings and
    `overage_tax_accrued_cents` is the sum of their `overage_tax_cents`; signings
    in `SUBMITTED`, `REJECTED` or `VOIDED` contribute nothing to either." — so
    1200000 then 800000 walk the pair from 0/5000000 to 2000000/3000000 with the
    forfeit and tax accumulators untouched at zero.

    Design: Difficulty/compensating_invariant/signing_pool_allocated_and_remaining_conserved_across_approve_and_void
    """
    bundle = _academy_pool_with_two_submitted_signings(api)

    checkpoint_0 = fixtures.read_pool(api, bundle["pool_id"])
    assert_money(checkpoint_0["allocated_cents"], 0, "allocated_cents")
    assert_money(checkpoint_0["remaining_cents"], 5000000, "remaining_cents")
    assert_money(checkpoint_0["effective_pool_cents"], 5000000, "effective_pool_cents")
    assert_pool_ledger_identity(checkpoint_0)
    assert_status(checkpoint_0, "OPEN", "SigningPool")

    first = fixtures.dispose_signing(api, bundle["first_signing_id"], "APPROVE")
    assert_money(first["pool_charge_cents"], 1200000, "pool_charge_cents")
    assert_money(first["overage_tax_cents"], 0, "overage_tax_cents")
    assert first["tier3_breach"] is False, (
        f"a bonus inside the pool cannot breach the third tier, got {first!r}"
    )
    checkpoint_1 = fixtures.read_pool(api, bundle["pool_id"])
    assert_money(checkpoint_1["allocated_cents"], 1200000, "allocated_cents")
    assert_money(checkpoint_1["remaining_cents"], 3800000, "remaining_cents")
    assert_pool_ledger_identity(checkpoint_1)

    second = fixtures.dispose_signing(api, bundle["second_signing_id"], "APPROVE")
    assert_money(second["pool_charge_cents"], 800000, "pool_charge_cents")
    assert_money(second["overage_tax_cents"], 0, "overage_tax_cents")
    assert second["tier3_breach"] is False, (
        f"a bonus inside the pool cannot breach the third tier, got {second!r}"
    )
    checkpoint_2 = fixtures.read_pool(api, bundle["pool_id"])
    assert_money(checkpoint_2["allocated_cents"], 2000000, "allocated_cents")
    assert_money(checkpoint_2["remaining_cents"], 3000000, "remaining_cents")
    assert_pool_ledger_identity(checkpoint_2)
    assert_money(checkpoint_2["forfeited_cents"], 0, "forfeited_cents")
    assert_money(checkpoint_2["overage_tax_accrued_cents"], 0, "overage_tax_accrued_cents")
    assert_status(checkpoint_2, "OPEN", "SigningPool")


def test_voiding_the_second_approval_restores_the_ledger_to_the_cent(api: ApiClient):
    """The void subtracts exactly what its approval added, and nothing else.

    PRD 3.9: "A `ComplianceOfficer` moves an `APPROVED` signing to the terminal
    state `VOIDED`, which removes that signing's `pool_charge_cents` from the
    pool's `allocated_cents` and its `overage_tax_cents` from the pool's
    `overage_tax_accrued_cents`; subtracts 250000 cents from the pool's
    `forfeited_cents` if and only if that signing's `tier3_breach` was true;
    recomputes `effective_pool_cents` and `remaining_cents`".  The ledger
    therefore lands back on its post-first-approval values, and the sibling
    approval is not dragged along, because PRD 2.10 limits the reversal:
    "Compensation reverses the ledger entries a transition created, and only
    those."

    Design: Difficulty/compensating_invariant/signing_pool_allocated_and_remaining_conserved_across_approve_and_void
    """
    bundle = _academy_pool_with_two_submitted_signings(api)
    fixtures.dispose_signing(api, bundle["first_signing_id"], "APPROVE")
    fixtures.dispose_signing(api, bundle["second_signing_id"], "APPROVE")

    voided = fixtures.dispose_signing(
        api, bundle["second_signing_id"], "VOID", note="medical review failed after approval"
    )
    assert_status(voided, "VOIDED", "InternationalSigning")
    assert_status(
        fixtures.read_signing(api, bundle["first_signing_id"]),
        "APPROVED",
        "InternationalSigning",
    )

    checkpoint_3 = fixtures.read_pool(api, bundle["pool_id"])
    assert_money(checkpoint_3["allocated_cents"], 1200000, "allocated_cents")
    assert_money(checkpoint_3["remaining_cents"], 3800000, "remaining_cents")
    assert_money(checkpoint_3["effective_pool_cents"], 5000000, "effective_pool_cents")
    assert_pool_ledger_identity(checkpoint_3)
    assert_money(checkpoint_3["forfeited_cents"], 0, "forfeited_cents")
    assert_money(checkpoint_3["overage_tax_accrued_cents"], 0, "overage_tax_accrued_cents")
    assert_status(checkpoint_3, "OPEN", "SigningPool")
