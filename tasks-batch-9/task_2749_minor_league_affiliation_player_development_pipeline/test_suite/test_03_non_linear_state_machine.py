"""Non-linear lifecycles: two parallel player dimensions, and one cyclic
inspection that re-enters a state it has already left."""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    ApiClient,
    assert_status,
    fixtures,
)

# ---------------------------------------------------------------------------
# Instance 1 — the two player standings move one at a time
# ---------------------------------------------------------------------------


def _nationals_club_with_a_fresh_player(api: ApiClient) -> dict:
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Fredericksburg Nationals",
            "level": "SINGLE_A",
            "market_city": "Fredericksburg",
            "meal_stipend_cents_per_day": 2700,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    player = fixtures.create_player(
        api,
        full_name="Marcus Vail",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-07-01",
    )
    clearance = fixtures.request_clearance(api, player["id"], "LEVEL_ASSIGNMENT")
    club["player_id"] = player["id"]
    club["first_clearance_id"] = clearance["id"]
    return club


def test_issuing_a_clearance_then_activating_moves_one_dimension_at_a_time(api):
    """Medical standing moves on the issue, roster standing on the activation.

    "A player carries two standings on the same row, and they evolve
    independently. **Roster standing**, held in `roster_status`, takes the
    values `RESERVE_LIST`, `ACTIVE` and `RESTRICTED`, and it moves on roster and
    assignment events. **Medical standing**, held in `medical_status`, takes the
    values `PENDING_CLEARANCE`, `CLEARED` and `RESTRICTED`, and it is a pure
    projection of the player's clearance records."

    Design: Difficulty/non_linear_state_machine/player_roster_and_medical_dimensions_advance_independently
    """
    bundle = _nationals_club_with_a_fresh_player(api)

    initial = fixtures.read_player(api, bundle["player_id"])
    assert initial["roster_status"] == "RESERVE_LIST", (
        f"a freshly registered player starts on the reserve list, got {initial['roster_status']}"
    )
    assert initial["medical_status"] == "PENDING_CLEARANCE", (
        f"medical standing starts pending, got {initial['medical_status']}"
    )

    fixtures.dispose_clearance(
        api,
        bundle["first_clearance_id"],
        "ISSUE",
        cleared_workload_ceiling_index=25.00,
        expires_on="2026-12-31",
    )

    after_issue = fixtures.read_player(api, bundle["player_id"])
    assert after_issue["medical_status"] == "CLEARED", (
        f"issuing a clearance clears the medical dimension, got {after_issue['medical_status']}"
    )
    assert after_issue["roster_status"] == "RESERVE_LIST", (
        "a medical event must not move roster standing, got "
        f"{after_issue['roster_status']}"
    )

    assignment = fixtures.create_assignment(
        api,
        bundle["player_id"],
        bundle["affiliate_id"],
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-08-05",
        end_date="2026-09-30",
    )
    fixtures.dispose_assignment(api, assignment["id"], "ACTIVATE")

    after_activate = fixtures.read_player(api, bundle["player_id"])
    assert after_activate["roster_status"] == "ACTIVE", (
        f"activation advances roster standing, got {after_activate['roster_status']}"
    )
    assert after_activate["medical_status"] == "CLEARED", (
        "a roster event must not move medical standing, got "
        f"{after_activate['medical_status']}"
    )


def test_a_denial_restricts_medical_standing_without_disturbing_the_active_assignment(api):
    """The player ends up ACTIVE on one dimension and RESTRICTED on the other.

    "The second of those is worth dwelling on, because a denial restricts the
    medical dimension without touching `roster_status` and without disturbing
    any active assignment; a player may therefore be simultaneously `ACTIVE` on
    the roster dimension and `RESTRICTED` on the medical dimension."

    Design: Difficulty/non_linear_state_machine/player_roster_and_medical_dimensions_advance_independently
    """
    bundle = _nationals_club_with_a_fresh_player(api)
    fixtures.dispose_clearance(
        api,
        bundle["first_clearance_id"],
        "ISSUE",
        cleared_workload_ceiling_index=25.00,
        expires_on="2026-12-31",
    )
    assignment = fixtures.create_assignment(
        api,
        bundle["player_id"],
        bundle["affiliate_id"],
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-08-05",
        end_date="2026-09-30",
    )
    fixtures.dispose_assignment(api, assignment["id"], "ACTIVATE")

    second_clearance = fixtures.request_clearance(api, bundle["player_id"], "LEVEL_ASSIGNMENT")
    fixtures.dispose_clearance(
        api,
        second_clearance["id"],
        "DENY",
        restriction_note="elbow inflammation flagged on re-screen",
    )

    player = fixtures.read_player(api, bundle["player_id"])
    assert player["medical_status"] == "RESTRICTED", (
        f"a denial restricts the medical dimension, got {player['medical_status']}"
    )
    assert player["roster_status"] == "ACTIVE", (
        f"the denial must leave roster standing alone, got {player['roster_status']}"
    )
    assert player["current_affiliate_id"] == bundle["affiliate_id"], (
        "the player stays attached to the receiving club, got "
        f"{player['current_affiliate_id']}"
    )

    assert_status(fixtures.read_assignment(api, assignment["id"]), "ACTIVE", "PlayerAssignment")

    first = fixtures.read_clearance(api, bundle["player_id"], bundle["first_clearance_id"])
    second = fixtures.read_clearance(api, bundle["player_id"], second_clearance["id"])
    assert_status(first, "ISSUED", "MedicalClearance")
    assert_status(second, "DENIED", "MedicalClearance")


# ---------------------------------------------------------------------------
# Instance 2 — the inspection remediation cycle
# ---------------------------------------------------------------------------


def _crawdads_club_with_a_minor_finding(api: ApiClient) -> dict:
    """The clock is moved to 2026-04-01 and a WEIGHT_ROOM 84 is filed that day."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Hickory Crawdads",
            "level": "HIGH_A",
            "market_city": "Hickory",
            "meal_stipend_cents_per_day": 2900,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )
    review = fixtures.file_facility_review(
        api, club["affiliate_id"], "WEIGHT_ROOM", "2026-04-01", 84
    )
    club["review"] = review
    club["review_id"] = review["id"]
    return club


def _submit_remediation(api: ApiClient, bundle: dict, narrative: str) -> dict:
    """Submit remediation as the club's own operator."""
    return fixtures.dispose_facility_review(
        api,
        bundle["review_id"],
        "SUBMIT_REMEDIATION",
        bundle["operator_headers"],
        remediation_note=narrative,
        note=narrative,
    )


def test_the_inspection_re_enters_remediation_submitted_through_closed_and_reopened(api):
    """One row visits REMEDIATION_SUBMITTED twice over a single cycle.

    "The officer may also reopen a `CLOSED` inspection, moving it to
    `REOPENED`, which increments `reopen_count`, resets `remediation_due_date`
    to fifteen days after the current logical clock date, and again recomputes
    the affiliate's deficiency tally and standing."

    Design: Difficulty/non_linear_state_machine/facility_review_remediation_reopen_cycle_returns_to_remediation_submitted
    """
    bundle = _crawdads_club_with_a_minor_finding(api)

    created = bundle["review"]
    assert created["deficiency_level"] == "MINOR", (
        f"a score of 84 bands to MINOR, got {created['deficiency_level']}"
    )
    assert_status(created, "OPEN", "FacilityStandardReview")
    assert created["remediation_due_date"] == "2026-05-31", (
        "a MINOR finding is due sixty days after the review date, got "
        f"{created['remediation_due_date']}"
    )
    assert created["reopen_count"] == 0, (
        f"a new inspection has never been reopened, got {created['reopen_count']}"
    )

    first_submission = _submit_remediation(api, bundle, "new racks installed")
    assert_status(first_submission, "REMEDIATION_SUBMITTED", "FacilityStandardReview")

    closed = fixtures.dispose_facility_review(api, bundle["review_id"], "CLOSE")
    assert_status(closed, "CLOSED", "FacilityStandardReview")

    reopened = fixtures.dispose_facility_review(api, bundle["review_id"], "REOPEN")
    assert_status(reopened, "REOPENED", "FacilityStandardReview")
    assert reopened["reopen_count"] == 1, (
        f"the reopen increments reopen_count to 1, got {reopened['reopen_count']}"
    )

    second_submission = _submit_remediation(api, bundle, "flooring replaced on re-inspection")
    assert_status(second_submission, "REMEDIATION_SUBMITTED", "FacilityStandardReview")


def test_the_reopen_rewrites_the_due_date_and_the_second_note_overwrites_the_first(api):
    """The deadline is re-derived from the clock, not from the review date.

    "The submission stores the operator's narrative in `remediation_note` and
    stamps `remediation_submitted_at` with the logical clock instant; a
    submission made from `REOPENED` overwrites both of those fields rather than
    accumulating a second copy."

    Design: Difficulty/non_linear_state_machine/facility_review_remediation_reopen_cycle_returns_to_remediation_submitted
    """
    bundle = _crawdads_club_with_a_minor_finding(api)
    _submit_remediation(api, bundle, "new racks installed")
    fixtures.dispose_facility_review(api, bundle["review_id"], "CLOSE")

    reopened = fixtures.dispose_facility_review(api, bundle["review_id"], "REOPEN")
    assert reopened["remediation_due_date"] == "2026-04-16", (
        "the reopen resets the deadline to fifteen days after the clock date "
        f"2026-04-01, got {reopened['remediation_due_date']}"
    )
    assert reopened["is_overdue"] is False, (
        "the clock has not passed the rewritten deadline, so nothing is overdue"
    )

    final = _submit_remediation(api, bundle, "flooring replaced on re-inspection")
    assert final["remediation_note"] == "flooring replaced on re-inspection", (
        "the second submission overwrites the first narrative, got "
        f"{final['remediation_note']!r}"
    )
    assert final["is_overdue"] is False, "a submitted remediation is never overdue here"

    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["facility_status"] == "PROVISIONAL", (
        "an open minor finding with no open major leaves the club PROVISIONAL, got "
        f"{affiliate['facility_status']}"
    )
    agreement = fixtures.read_agreement(api, bundle["affiliate_id"], bundle["agreement_id"])
    assert agreement["posture"] == "OPEN", (
        f"a MINOR deficiency never freezes the posture, got {agreement['posture']}"
    )
