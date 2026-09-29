"""Boundaries walked on both sides: a strict counter comparison and the
inclusive score band that separates a clean inspection from a minor one."""

from typing import List

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_deficiency_banding,
    assert_status,
    factories,
    fixtures,
    validate_error,
)

# ---------------------------------------------------------------------------
# Instance 1 — active_roster_count strictly below roster_limit
# ---------------------------------------------------------------------------


def _emeralds_club_with_three_pending_assignments(api: ApiClient) -> dict:
    """A club capped at two slots holding three cleared, pending players."""
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Eugene Emeralds",
            "level": "HIGH_A",
            "market_city": "Eugene",
            "meal_stipend_cents_per_day": 2800,
            "roster_limit": 2,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    candidates: List[dict] = []
    for name in ("Roster One", "Roster Two", "Roster Three"):
        candidates.append(
            fixtures.pending_assignment(
                api,
                club["affiliate_id"],
                player_overrides={
                    "full_name": name,
                    "origin": "DOMESTIC_DRAFT",
                    "signed_date": "2025-06-10",
                },
                effective_date="2026-08-05",
                end_date="2026-09-30",
            )
        )
    club["candidates"] = candidates
    return club


def test_the_roster_admits_at_one_below_the_limit_and_refuses_at_the_limit(api):
    """Two admissions then one refusal across a strict integer comparison.

    "For a `LEVEL` or `COMPLEX` assignment the club's `active_roster_count` must
    be strictly below its `roster_limit` (`ERR_ROSTER_LIMIT_EXCEEDED`); for a
    `REHAB` assignment the club's `rehab_assignment_count` must be strictly
    below the organization's rehab slot allowance of three concurrent rehab
    assignments per club (`ERR_REHAB_SLOT_LIMIT_EXCEEDED`)."

    Design: Difficulty/boundary_precision_check/roster_limit_blocks_at_exactly_the_limit_and_admits_at_limit_minus_one
    """
    bundle = _emeralds_club_with_three_pending_assignments(api)
    assert bundle["affiliate"]["roster_limit"] == 2, (
        "the explicit input overrides the HIGH_A default of 30, got "
        f"{bundle['affiliate']['roster_limit']}"
    )

    first = fixtures.dispose_assignment(
        api, bundle["candidates"][0]["assignment_id"], "ACTIVATE"
    )
    assert_status(first, "ACTIVE", "PlayerAssignment")
    assert fixtures.read_affiliate(api, bundle["affiliate_id"])["active_roster_count"] == 1

    second = fixtures.dispose_assignment(
        api, bundle["candidates"][1]["assignment_id"], "ACTIVATE"
    )
    assert_status(second, "ACTIVE", "PlayerAssignment")
    assert fixtures.read_affiliate(api, bundle["affiliate_id"])["active_roster_count"] == 2

    refused = api.dispose_assignment(
        bundle["candidates"][2]["assignment_id"],
        factories.disposition_payload("ACTIVATE"),
        FARM_DIRECTOR_HEADERS,
    )
    validate_error(refused, ApiErrorId.ERR_ROSTER_LIMIT_EXCEEDED.value, 409)


def test_the_refused_third_activation_charges_and_advances_nothing(api):
    """At count two the comparison fails and no side effect is left behind.

    "`roster_limit` bounds how many level or complex assignments the club may
    carry concurrently; it accepts integers from 1 through 40, and when it is
    omitted the server applies the league default for the declared level — 28
    for both `TRIPLE_A` and `DOUBLE_A`, 30 for both `HIGH_A` and `SINGLE_A`, 35
    for `COMPLEX`, and 40 for `DOMINICAN_ACADEMY`."

    Design: Difficulty/boundary_precision_check/roster_limit_blocks_at_exactly_the_limit_and_admits_at_limit_minus_one
    """
    bundle = _emeralds_club_with_three_pending_assignments(api)
    fixtures.dispose_assignment(api, bundle["candidates"][0]["assignment_id"], "ACTIVATE")
    fixtures.dispose_assignment(api, bundle["candidates"][1]["assignment_id"], "ACTIVATE")

    third = bundle["candidates"][2]
    api.dispose_assignment(
        third["assignment_id"],
        factories.disposition_payload("ACTIVATE"),
        FARM_DIRECTOR_HEADERS,
    )

    assert_status(
        fixtures.read_assignment(api, third["assignment_id"]),
        "PENDING_CLEARANCE",
        "PlayerAssignment",
    )
    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["active_roster_count"] == 2, (
        f"the counter must stay at two, got {affiliate['active_roster_count']}"
    )
    player = fixtures.read_player(api, third["player_id"])
    assert player["roster_status"] == "RESERVE_LIST", (
        f"the refused player stays on the reserve list, got {player['roster_status']}"
    )
    assert player["option_years_used"] == 0, (
        f"the failed activation charged no option year, got {player['option_years_used']}"
    )


# ---------------------------------------------------------------------------
# Instance 2 — the 85/84 deficiency band
# ---------------------------------------------------------------------------


def _wind_surge_club(api: ApiClient) -> dict:
    """A licensed DOUBLE_A club with no inspection history, clock at 2026-04-01."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    return fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Wichita Wind Surge",
            "level": "DOUBLE_A",
            "market_city": "Wichita",
            "meal_stipend_cents_per_day": 3000,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )


def test_a_score_of_eighty_five_closes_on_the_spot_with_no_remediation_clock(api):
    """Exactly at the band edge the finding is clean.

    "A clean inspection never waits for anyone: when `deficiency_level` comes
    out `NONE`, the row is persisted directly in status `CLOSED` with
    `remediation_due_date` left null."

    Design: Difficulty/boundary_precision_check/facility_deficiency_level_boundary_at_score_85_and_84
    """
    club = _wind_surge_club(api)
    assert_decimal(club["affiliate"]["facility_score"], "100.00", 2, "facility_score with no review")
    assert club["affiliate"]["facility_status"] == "COMPLIANT", (
        f"a club with no inspection is COMPLIANT, got {club['affiliate']['facility_status']}"
    )

    clean = fixtures.file_facility_review(api, club["affiliate_id"], "CLUBHOUSE", "2026-04-01", 85)
    assert clean["deficiency_level"] == "NONE", (
        f"a score of exactly 85 bands to NONE, got {clean['deficiency_level']}"
    )
    assert_deficiency_banding(clean)
    assert_status(clean, "CLOSED", "FacilityStandardReview")
    assert clean["remediation_due_date"] is None, (
        f"a clean finding carries no deadline, got {clean['remediation_due_date']!r}"
    )
    assert clean["is_overdue"] is False, "a CLOSED inspection is never overdue"

    affiliate = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_decimal(affiliate["facility_score"], "85.00", 2, "facility_score after the 85")
    assert affiliate["facility_status"] == "COMPLIANT", (
        f"a clean finding leaves the club COMPLIANT, got {affiliate['facility_status']}"
    )


def test_a_score_of_eighty_four_opens_a_sixty_day_clock_and_averages_to_eighty_four_fifty(api):
    """One below the edge the finding is MINOR, and the mean rounds to two places.

    "A deficient inspection is persisted in status `OPEN` with a remediation
    clock attached: a `MAJOR` finding gives the club thirty days from the
    `review_date` to remediate, and a `MINOR` finding gives it sixty days, and
    that deadline is written into `remediation_due_date`."

    Design: Difficulty/boundary_precision_check/facility_deficiency_level_boundary_at_score_85_and_84
    """
    club = _wind_surge_club(api)
    fixtures.file_facility_review(api, club["affiliate_id"], "CLUBHOUSE", "2026-04-01", 85)

    minor = fixtures.file_facility_review(
        api, club["affiliate_id"], "WEIGHT_ROOM", "2026-04-01", 84
    )
    assert minor["deficiency_level"] == "MINOR", (
        f"a score of 84 bands to MINOR, got {minor['deficiency_level']}"
    )
    assert_deficiency_banding(minor)
    assert_status(minor, "OPEN", "FacilityStandardReview")
    assert minor["remediation_due_date"] == "2026-05-31", (
        f"sixty days after 2026-04-01 is 2026-05-31, got {minor['remediation_due_date']}"
    )
    assert minor["is_overdue"] is False, "the clock has not passed the deadline"

    affiliate = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_decimal(affiliate["facility_score"], "84.50", 2, "facility_score over two categories")
    assert affiliate["facility_status"] == "PROVISIONAL", (
        "no open major and one open minor makes the club PROVISIONAL, got "
        f"{affiliate['facility_status']}"
    )
    assert affiliate["open_major_deficiency_count"] == 0, (
        f"a MINOR finding is not a major, got {affiliate['open_major_deficiency_count']}"
    )

    agreement = fixtures.read_agreement(api, club["affiliate_id"], club["agreement_id"])
    assert agreement["posture"] == "OPEN", (
        f"only a DEFICIENT rollup freezes the posture, got {agreement['posture']}"
    )
