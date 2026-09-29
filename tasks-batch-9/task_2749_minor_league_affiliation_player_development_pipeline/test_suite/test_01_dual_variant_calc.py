"""Dual-variant derived numbers: the two workload figures and the two
expense-allocation variants."""

from decimal import Decimal

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    ApiClient,
    assert_decimal,
    assert_money,
    assert_status,
    fixtures,
    validate_paginated,
)

# ---------------------------------------------------------------------------
# Instance 1 — workload_index versus workload_index_projected
# ---------------------------------------------------------------------------


def _double_a_player_with_two_non_rehab_outings(api: ApiClient) -> dict:
    """A DOUBLE_A club, an ACTIVE assignment and plan, and two logged outings.

    The logical clock is left at its startup default, so the rolling window
    covers both outings.
    """
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Rockford Rivets",
            "level": "DOUBLE_A",
            "market_city": "Rockford",
            "meal_stipend_cents_per_day": 3000,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 5000000,
            "minimum_active_players": 0,
        },
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Diego Marte",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2024-06-10",
            "service_days_accrued": 200,
        },
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-07-20",
        end_date="2026-09-30",
        workload_ceiling_index=12.00,
    )
    plan = fixtures.active_plan_on(
        api,
        bundle["assignment_id"],
        target_level="TRIPLE_A",
        curriculum_modules=[
            "MOD_MECHANICS",
            "MOD_SEQUENCING",
            "MOD_RECOVERY",
            "MOD_GAMEPLAN",
        ],
        workload_limit_weekly_index=1.50,
    )
    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-07-28",
        pitches_thrown=100,
        innings_pitched=3.0,
        high_intensity_minutes=10,
        is_rehab_outing=False,
    )
    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-07-30",
        pitches_thrown=80,
        innings_pitched=1.0,
        high_intensity_minutes=0,
        is_rehab_outing=False,
    )
    club.update(bundle)
    club.update(plan)
    return club


def test_rehab_outing_is_dropped_from_the_actual_index_but_halved_into_the_projection(api):
    """The two figures diverge over one identical set of three outings.

    "The player's `workload_index` sums the contributions of only those
    qualifying outings whose `is_rehab_outing` is false, adds no plan allowance
    at all, rounds the sum half-up to two decimal places, and finally takes the
    smaller of that rounded figure and the system ceiling of `25.00`."

    Design: Difficulty/dual_variant_calc/workload_index_actual_vs_projected_diverge_for_same_logs
    """
    bundle = _double_a_player_with_two_non_rehab_outings(api)

    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-08-01",
        MEDICAL_DIRECTOR_HEADERS,
        pitches_thrown=40,
        innings_pitched=2.0,
        high_intensity_minutes=12,
        is_rehab_outing=True,
    )

    player = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(player["workload_index"], "1.27", 2, "Player.workload_index")
    assert_decimal(
        player["workload_index_projected"], "2.94", 2, "Player.workload_index_projected"
    )

    delta = Decimal(str(player["workload_index_projected"])) - Decimal(
        str(player["workload_index"])
    )
    assert_decimal(delta, "1.67", 2, "workload_index_projected - workload_index")


def test_the_projection_moves_with_the_rehab_outing_while_the_actual_index_stands_still(api):
    """Only the projected figure changes when a rehab outing is appended.

    "The player's `workload_index_projected` sums the contributions of every
    qualifying outing, taking rehab outings at half weight — each rehab
    outing's contribution is multiplied by `0.50` while each non-rehab
    outing's contribution is taken in full — then adds a forward-looking plan
    allowance equal to the `workload_limit_weekly_index` of the player's
    `ACTIVE` development plan, or zero when the player has no `ACTIVE` plan,
    then rounds half-up to two decimal places and takes the smaller of that
    figure and `25.00`."

    Design: Difficulty/dual_variant_calc/workload_index_actual_vs_projected_diverge_for_same_logs
    """
    bundle = _double_a_player_with_two_non_rehab_outings(api)

    before = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(before["workload_index"], "1.27", 2, "workload_index before the rehab log")
    assert_decimal(
        before["workload_index_projected"],
        "2.77",
        2,
        "workload_index_projected before the rehab log",
    )

    fixtures.log_outing(
        api,
        bundle["assignment_id"],
        "2026-08-01",
        MEDICAL_DIRECTOR_HEADERS,
        pitches_thrown=40,
        innings_pitched=2.0,
        high_intensity_minutes=12,
        is_rehab_outing=True,
    )

    after = fixtures.read_player(api, bundle["player_id"])
    assert_decimal(after["workload_index"], "1.27", 2, "workload_index after the rehab log")
    assert_decimal(
        after["workload_index_projected"],
        "2.94",
        2,
        "workload_index_projected after the rehab log",
    )

    rows, meta = validate_paginated(
        api.list_workload_logs(bundle["assignment_id"], FARM_DIRECTOR_HEADERS)
    )
    assert meta["total_count"] == 3, f"expected three logged outings, got {meta['total_count']}"
    assert len(rows) == 3, f"expected three rows in the page, got {len(rows)}"
    assert meta["has_more"] is False, "a three-row page under the default limit has no more"


# ---------------------------------------------------------------------------
# Instance 2 — provisional versus final expense allocation
# ---------------------------------------------------------------------------

_BELOIT_AFFILIATE = {
    "name": "Beloit Sky Carp",
    "level": "HIGH_A",
    "market_city": "Beloit",
    "meal_stipend_cents_per_day": 2800,
}

_BELOIT_AGREEMENT = {
    "term_start_date": "2026-01-01",
    "term_end_date": "2026-12-31",
    "facility_standard_tier": "TIER_2",
    "club_reimbursement_cap_cents": 1800000,
    "minimum_active_players": 0,
    "housing_expense_cents": 1200000,
    "meal_expense_cents": 640000,
    "travel_expense_cents": 355000,
    "upkeep_expense_cents": 480000,
}


def _beloit_draft_agreement(api: ApiClient) -> dict:
    affiliate = fixtures.create_affiliate(api, COMPLIANCE_OFFICER_HEADERS, **_BELOIT_AFFILIATE)
    agreement = fixtures.create_agreement(api, affiliate["id"], **_BELOIT_AGREEMENT)
    return {"affiliate_id": affiliate["id"], "agreement_id": agreement["id"]}


def test_submission_drains_one_aggregate_cap_while_settlement_splits_it_pro_rata(api):
    """One cap, two topologies, and byte-identical expense inputs.

    "The provisional variant treats `club_reimbursement_cap_cents` as one
    aggregate bucket and drains it in a fixed category order — housing first,
    then meals, then travel, then facility upkeep, never in identifier order."

    Design: Difficulty/dual_variant_calc/expense_allocation_provisional_vs_final_cap_application
    """
    bundle = _beloit_draft_agreement(api)

    submitted = fixtures.submit_agreement(api, bundle["agreement_id"], bundle["affiliate_id"])
    assert_money(
        submitted["provisional_club_obligation_cents"],
        1759000,
        "provisional_club_obligation_cents",
    )
    assert_money(submitted["affiliate_overflow_cents"], 0, "affiliate_overflow_cents at submission")

    fixtures.activate_agreement(api, bundle["agreement_id"])
    settled = fixtures.dispose_agreement(api, bundle["agreement_id"], "SETTLE")

    assert_money(
        settled["final_club_obligation_cents"], 1378231, "final_club_obligation_cents"
    )
    assert_money(
        settled["affiliate_overflow_cents"], 380769, "affiliate_overflow_cents at settlement"
    )
    assert_money(
        settled["provisional_club_obligation_cents"],
        1759000,
        "provisional_club_obligation_cents after settlement",
    )
    assert (
        settled["provisional_club_obligation_cents"]
        - settled["final_club_obligation_cents"]
        == settled["affiliate_overflow_cents"]
    ), (
        "the whole variant delta must land in affiliate_overflow_cents: "
        f"{settled['provisional_club_obligation_cents']} - "
        f"{settled['final_club_obligation_cents']} != {settled['affiliate_overflow_cents']}"
    )


def test_settlement_is_a_self_transition_that_only_moves_the_settlement_ledger(api):
    """Only the housing line exceeds its own sub-cap, and the licence stays ACTIVE.

    "Settlement is a self-transition available to a `ComplianceOfficer` on a
    licence that is `ACTIVE`: the licence remains `ACTIVE` and only its
    settlement ledger changes."

    Design: Difficulty/dual_variant_calc/expense_allocation_provisional_vs_final_cap_application
    """
    bundle = _beloit_draft_agreement(api)
    fixtures.submit_agreement(api, bundle["agreement_id"], bundle["affiliate_id"])
    fixtures.activate_agreement(api, bundle["agreement_id"])

    settled = fixtures.dispose_agreement(api, bundle["agreement_id"], "SETTLE")

    assert_status(settled, "ACTIVE", "AffiliationAgreement")
    assert settled["settlement_status"] == "SETTLED", (
        f"settlement_status must move to SETTLED, got {settled['settlement_status']}"
    )

    # HOUSING is the only line clipped by its pro-rata sub-cap: 900000 -> 519231,
    # while MEALS 384000, TRAVEL 355000 and FACILITY_UPKEEP 120000 pass through.
    assert_money(
        settled["final_club_obligation_cents"],
        519231 + 384000 + 355000 + 120000,
        "final obligation as the sum of the four final lines",
    )
    assert_money(
        settled["affiliate_overflow_cents"],
        (900000 - 519231),
        "overflow is exactly the clipped housing remainder",
    )
