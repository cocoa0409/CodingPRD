"""Multi-level cascades: one medical revocation and one assignment revocation."""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    ApiClient,
    assert_option_year_conservation,
    assert_status,
    fixtures,
    validate_paginated,
)

# ---------------------------------------------------------------------------
# Instance 1 — a clearance revocation propagating five levels outward
# ---------------------------------------------------------------------------


def _patriots_club_with_one_active_player(api: ApiClient) -> dict:
    """A DOUBLE_A club whose staffing floor of one is met by a single player."""
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Somerset Patriots",
            "level": "DOUBLE_A",
            "market_city": "Bridgewater",
            "meal_stipend_cents_per_day": 3100,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 1,
        },
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Tobias Renn",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2024-06-10",
            "service_days_accrued": 150,
        },
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-08-05",
        end_date="2026-09-30",
    )
    plan = fixtures.active_plan_on(
        api,
        bundle["assignment_id"],
        target_level="TRIPLE_A",
        curriculum_modules=["MOD_MECHANICS", "MOD_SEQUENCING"],
    )
    club.update(bundle)
    club.update(plan)
    return club


def test_revoking_the_clearance_suspends_the_assignment_and_restricts_the_player(api):
    """The cascade runs clearance, medical standing, assignment, roster, club.

    "It moves every assignment for that player in status `ACTIVE` whose
    required clearance type matches the revoked clearance's `clearance_type` to
    `SUSPENDED`. It moves the player's `roster_status` to `RESTRICTED` and
    clears `current_affiliate_id`."

    Design: Difficulty/transitive_cascade/clearance_revocation_cascades_to_assignment_plan_roster_and_posture
    """
    bundle = _patriots_club_with_one_active_player(api)
    before = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert before["active_roster_count"] == 1, (
        f"one activation puts one player on the roster, got {before['active_roster_count']}"
    )

    revoked = fixtures.dispose_clearance(
        api,
        bundle["clearance_id"],
        "REVOKE",
        restriction_note="UCL sprain confirmed on MRI",
    )
    assert_status(revoked, "REVOKED", "MedicalClearance")

    player = fixtures.read_player(api, bundle["player_id"])
    assert player["medical_status"] == "RESTRICTED", (
        f"the revocation restricts medical standing, got {player['medical_status']}"
    )
    assert player["roster_status"] == "RESTRICTED", (
        f"the revocation also restricts roster standing, got {player['roster_status']}"
    )
    assert player["current_affiliate_id"] is None, (
        f"the player is detached from the club, got {player['current_affiliate_id']!r}"
    )

    assert_status(
        fixtures.read_assignment(api, bundle["assignment_id"]), "SUSPENDED", "PlayerAssignment"
    )

    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["active_roster_count"] == 0, (
        f"the suspended assignment vacates its slot, got {affiliate['active_roster_count']}"
    )
    assert affiliate["reserve_list_count"] == 0, (
        f"a restricted, unattached player fills no reserve slot here, got {affiliate['reserve_list_count']}"
    )


def test_the_clearance_revocation_leaves_the_plan_and_the_option_year_untouched(api):
    """The licence posture drops but the plan and the option-year ledger stand.

    "Any development plan attached to a newly suspended assignment stays
    `ACTIVE` rather than lapsing, but the player's `promotion_readiness` is
    recomputed."

    Design: Difficulty/transitive_cascade/clearance_revocation_cascades_to_assignment_plan_roster_and_posture
    """
    bundle = _patriots_club_with_one_active_player(api)
    before = fixtures.read_agreement(api, bundle["affiliate_id"], bundle["agreement_id"])
    assert before["posture"] == "OPEN", (
        f"one active player meets the floor of one, so posture is OPEN, got {before['posture']}"
    )

    fixtures.dispose_clearance(
        api,
        bundle["clearance_id"],
        "REVOKE",
        restriction_note="UCL sprain confirmed on MRI",
    )

    agreement = fixtures.read_agreement(api, bundle["affiliate_id"], bundle["agreement_id"])
    assert agreement["posture"] == "RESTRICTED", (
        "falling below minimum_active_players drives the posture down, got "
        f"{agreement['posture']}"
    )
    assert_status(agreement, "ACTIVE", "AffiliationAgreement")

    assert_status(
        fixtures.read_plan(api, bundle["assignment_id"], bundle["plan_id"]),
        "ACTIVE",
        "DevelopmentPlan",
    )

    option_years = fixtures.option_years_for(api, bundle["assignment_id"])
    assert len(option_years) == 1, f"the activation charged one option year, got {option_years}"
    assert_status(option_years[0], "CHARGED", "OptionYearRecord")

    player = fixtures.read_player(api, bundle["player_id"])
    assert player["option_years_used"] == 1, (
        f"a suspension returns no option year, got {player['option_years_used']}"
    )
    assert player["option_years_remaining"] == 2, (
        f"two option years remain, got {player['option_years_remaining']}"
    )
    assert_option_year_conservation(player)


# ---------------------------------------------------------------------------
# Instance 2 — an assignment revocation compensating inside its own aggregate
# ---------------------------------------------------------------------------


def _bulls_club_with_a_charged_active_assignment(api: ApiClient) -> dict:
    """A TRIPLE_A club, clock at 2026-04-01, one 91-day ACTIVE assignment."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Durham Bulls",
            "level": "TRIPLE_A",
            "market_city": "Durham",
            "meal_stipend_cents_per_day": 3300,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    bundle = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Ander Solis",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2023-06-12",
            "service_days_accrued": 300,
        },
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-04-01",
        end_date="2026-06-30",
    )
    plan = fixtures.active_plan_on(
        api,
        bundle["assignment_id"],
        target_level="TRIPLE_A",
        curriculum_modules=["MOD_MECHANICS", "MOD_GAMEPLAN"],
    )
    club.update(bundle)
    club.update(plan)
    return club


def test_revoking_an_active_assignment_rescinds_the_option_year_it_charged(api):
    """The charge is undone and the day snapshot survives on the rescinded row.

    "From `ACTIVE`, revoking moves the row to `REVOKED` and unwinds everything
    the activation did: every option-year record whose
    `triggering_assignment_id` is this assignment and whose status is `CHARGED`
    moves to `RESCINDED`, which restores the player's `option_years_used` and
    `option_years_remaining`; the assignment's `option_year_charged` flips back
    to false".

    Design: Difficulty/transitive_cascade/assignment_revocation_cascades_to_option_year_roster_and_transaction_report
    """
    bundle = _bulls_club_with_a_charged_active_assignment(api)

    before = fixtures.read_assignment(api, bundle["assignment_id"])
    assert before["projected_optional_days"] == 91, (
        "2026-04-01 through 2026-06-30 inclusive is 91 days, got "
        f"{before['projected_optional_days']}"
    )
    assert before["option_year_charged"] is True, "a 91-day level assignment charges an option year"

    revoked = fixtures.dispose_assignment(
        api,
        bundle["assignment_id"],
        "REVOKE",
        note="assignment rescinded before reporting deadline",
    )
    assert_status(revoked, "REVOKED", "PlayerAssignment")
    assert revoked["option_year_charged"] is False, (
        f"the charge flag flips back, got {revoked['option_year_charged']}"
    )

    option_years = fixtures.option_years_for(api, bundle["assignment_id"])
    assert len(option_years) == 1, f"the record is rescinded, not deleted, got {option_years}"
    assert_status(option_years[0], "RESCINDED", "OptionYearRecord")
    assert option_years[0]["optional_days"] == 91, (
        f"the charge-time snapshot is preserved, got {option_years[0]['optional_days']}"
    )

    player = fixtures.read_player(api, bundle["player_id"])
    assert player["option_years_used"] == 0, (
        f"the option year is returned to the player, got {player['option_years_used']}"
    )
    assert player["option_years_remaining"] == 3, (
        f"all three option years are available again, got {player['option_years_remaining']}"
    )
    assert_option_year_conservation(player)


def test_revoking_voids_the_pending_report_and_mints_one_revocation_report(api):
    """A create-and-void pair on the same assignment, plus a lapsed plan.

    "every transaction report for this assignment in status `PENDING`, `FILED`
    or `REJECTED_BY_LEAGUE` moves to `VOIDED`, and exactly one new report is
    created in status `PENDING` with `transaction_type` `REVOCATION`; any
    development plan on the assignment in `DRAFT`, `ACTIVE` or
    `REVISION_REQUESTED` moves to `LAPSED`".

    Design: Difficulty/transitive_cascade/assignment_revocation_cascades_to_option_year_roster_and_transaction_report
    """
    bundle = _bulls_club_with_a_charged_active_assignment(api)

    original = fixtures.pending_report_for(api, bundle["assignment_id"])
    assert original["transaction_type"] == "OPTIONAL_ASSIGNMENT", (
        f"an INITIAL movement reports as OPTIONAL_ASSIGNMENT, got {original['transaction_type']}"
    )
    assert original["filing_deadline"] == "2026-04-03", (
        "the deadline is two days after the effective date, got "
        f"{original['filing_deadline']}"
    )

    fixtures.dispose_assignment(
        api,
        bundle["assignment_id"],
        "REVOKE",
        note="assignment rescinded before reporting deadline",
    )

    rows, meta = validate_paginated(
        api.list_transaction_reports(bundle["assignment_id"], COMPLIANCE_OFFICER_HEADERS)
    )
    assert meta["total_count"] == 2, (
        f"the void and the replacement leave two reports, got {meta['total_count']}"
    )
    voided = [r for r in rows if r["id"] == original["id"]]
    assert len(voided) == 1, f"the original report is still readable, got {rows}"
    assert_status(voided[0], "VOIDED", "TransactionReport")

    replacements = [r for r in rows if r["id"] != original["id"]]
    assert len(replacements) == 1, f"exactly one replacement is minted, got {replacements}"
    assert replacements[0]["transaction_type"] == "REVOCATION", (
        f"the replacement reports the revocation, got {replacements[0]['transaction_type']}"
    )
    assert_status(replacements[0], "PENDING", "TransactionReport")

    assert_status(
        fixtures.read_plan(api, bundle["assignment_id"], bundle["plan_id"]),
        "LAPSED",
        "DevelopmentPlan",
    )

    player = fixtures.read_player(api, bundle["player_id"])
    assert player["roster_status"] == "RESERVE_LIST", (
        f"the player returns to the reserve list, got {player['roster_status']}"
    )
    assert player["current_affiliate_id"] is None, (
        f"the player is detached from the club, got {player['current_affiliate_id']!r}"
    )

    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["active_roster_count"] == 0, (
        f"the revoked assignment vacates its slot, got {affiliate['active_roster_count']}"
    )
    agreement = fixtures.read_agreement(api, bundle["affiliate_id"], bundle["agreement_id"])
    assert agreement["posture"] == "OPEN", (
        f"a floor of zero keeps the posture OPEN throughout, got {agreement['posture']}"
    )
