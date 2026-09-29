"""Pairs of simultaneously violated rules where only the higher-priority one
may surface, with a control call proving the lower one is genuinely armed."""

from test_helpers import (
    COMPLIANCE_OFFICER_HEADERS,
    FARM_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_decimal,
    assert_status,
    factories,
    fixtures,
    validate_error,
)


def _activate(api: ApiClient, assignment_id: str):
    """Raw ACTIVATE call, so failures can be inspected rather than raised."""
    return api.dispose_assignment(
        assignment_id, factories.disposition_payload("ACTIVATE"), FARM_DIRECTOR_HEADERS
    )


# ---------------------------------------------------------------------------
# Instance 1 — the state check outranks the roster capacity check
# ---------------------------------------------------------------------------


def _red_sox_club_at_its_roster_limit_of_one(api: ApiClient) -> dict:
    """Player A active at a club capped at one slot, player B still pending."""
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Salem Red Sox",
            "level": "SINGLE_A",
            "market_city": "Salem",
            "meal_stipend_cents_per_day": 2600,
            "roster_limit": 1,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_2",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    player_a = fixtures.active_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Player A Nolan",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-08-05",
        end_date="2026-09-30",
    )
    player_b = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Player B Ochoa",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2025-06-10",
        },
        effective_date="2026-08-05",
        end_date="2026-09-30",
    )
    club["assignment_a_id"] = player_a["assignment_id"]
    club["assignment_b_id"] = player_b["assignment_id"]
    return club


def test_re_activating_an_active_assignment_reports_the_state_error_not_the_full_roster(api):
    """Both rules are violated at once, and only the earlier one is reported.

    "The target resource is in a state from which the requested action is a
    declared transition, otherwise the state error for that resource type
    (409). This check guards every disposition endpoint plus the two
    child-creation endpoints that attach a development plan or a workload outing
    to an assignment."

    Design: Difficulty/priority_pair_validation_conflict/assignment_activate_state_error_precedes_roster_capacity_error
    """
    bundle = _red_sox_club_at_its_roster_limit_of_one(api)

    response = _activate(api, bundle["assignment_a_id"])
    validate_error(response, ApiErrorId.ERR_INVALID_ASSIGNMENT_STATE.value, 409)

    # Control: removing only the state violation unmasks the capacity rule.
    control = _activate(api, bundle["assignment_b_id"])
    validate_error(control, ApiErrorId.ERR_ROSTER_LIMIT_EXCEEDED.value, 409)


def test_neither_rejected_activation_moves_a_status_or_a_counter(api):
    """A refused activation leaves both assignments and the counter as they were.

    "Every capacity comparison is made against the counters as they stand
    *before* this activation increments them."

    Design: Difficulty/priority_pair_validation_conflict/assignment_activate_state_error_precedes_roster_capacity_error
    """
    bundle = _red_sox_club_at_its_roster_limit_of_one(api)

    _activate(api, bundle["assignment_a_id"])
    _activate(api, bundle["assignment_b_id"])

    assert_status(
        fixtures.read_assignment(api, bundle["assignment_a_id"]), "ACTIVE", "PlayerAssignment"
    )
    assert_status(
        fixtures.read_assignment(api, bundle["assignment_b_id"]),
        "PENDING_CLEARANCE",
        "PlayerAssignment",
    )

    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["active_roster_count"] == 1, (
        f"no failed call may mutate a counter, got {affiliate['active_roster_count']}"
    )


# ---------------------------------------------------------------------------
# Instance 2 — the frozen posture outranks the missing clearance
# ---------------------------------------------------------------------------


def _lookouts_club_frozen_over_an_uncleared_player(api: ApiClient) -> dict:
    """A club frozen by a MAJOR finding, holding one assignment and no clearance."""
    fixtures.set_clock(api, "2026-04-01T00:00:00Z")
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Chattanooga Lookouts",
            "level": "DOUBLE_A",
            "market_city": "Chattanooga",
            "meal_stipend_cents_per_day": 3000,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
        creator_headers=COMPLIANCE_OFFICER_HEADERS,
    )
    assert club["agreement"]["posture"] == "OPEN", (
        f"the licence activates OPEN before any inspection, got {club['agreement']['posture']}"
    )
    player = fixtures.create_player(
        api,
        full_name="Isaias Fuentes",
        origin="DOMESTIC_DRAFT",
        signed_date="2025-06-10",
    )
    assignment = fixtures.create_assignment(
        api,
        player["id"],
        club["affiliate_id"],
        assignment_type="LEVEL",
        movement_reason="INITIAL",
        effective_date="2026-04-05",
        end_date="2026-06-30",
    )
    review = fixtures.file_facility_review(
        api, club["affiliate_id"], "MEDICAL_ROOM", "2026-04-01", 60
    )
    club["player_id"] = player["id"]
    club["assignment_id"] = assignment["id"]
    club["review"] = review
    club["review_id"] = review["id"]
    return club


def test_the_frozen_posture_masks_the_missing_clearance_until_the_deficiency_is_closed(api):
    """Repairing the facility unmasks the medical rule that was hiding behind it.

    "`FROZEN` blocks every child write at the affiliate: creating an assignment,
    activating or resuming an assignment, proposing a staff allocation, and
    approving an international signing at that academy — each rejected with
    `ERR_AGREEMENT_POSTURE_FROZEN`. Facility-inspection dispositions are
    deliberately exempt from the posture gate, because a major deficiency is
    itself what freezes the posture, and gating remediation submission on
    posture would leave the deficiency permanently unrecoverable."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_error_precedes_missing_medical_clearance_error
    """
    bundle = _lookouts_club_frozen_over_an_uncleared_player(api)

    assert bundle["review"]["deficiency_level"] == "MAJOR", (
        f"a score of 60 bands to MAJOR, got {bundle['review']['deficiency_level']}"
    )
    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["facility_status"] == "DEFICIENT", (
        f"an open major finding is DEFICIENT, got {affiliate['facility_status']}"
    )
    frozen = fixtures.read_agreement(api, bundle["affiliate_id"], bundle["agreement_id"])
    assert frozen["posture"] == "FROZEN", (
        f"a DEFICIENT club freezes its licence, got {frozen['posture']}"
    )

    first = _activate(api, bundle["assignment_id"])
    validate_error(first, ApiErrorId.ERR_AGREEMENT_POSTURE_FROZEN.value, 409)

    # The remediation is accepted despite the freeze: inspections are exempt.
    fixtures.dispose_facility_review(
        api,
        bundle["review_id"],
        "SUBMIT_REMEDIATION",
        bundle["operator_headers"],
        remediation_note="training room rebuilt to TIER_1 spec",
        note="training room rebuilt to TIER_1 spec",
    )
    fixtures.dispose_facility_review(api, bundle["review_id"], "CLOSE")

    repaired = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert repaired["facility_status"] == "COMPLIANT", (
        f"closing the only finding leaves the club COMPLIANT, got {repaired['facility_status']}"
    )
    assert_decimal(repaired["facility_score"], "60.00", 2, "Affiliate.facility_score")
    thawed = fixtures.read_agreement(api, bundle["affiliate_id"], bundle["agreement_id"])
    assert thawed["posture"] == "OPEN", (
        f"the close re-derives the posture back to OPEN, got {thawed['posture']}"
    )

    second = _activate(api, bundle["assignment_id"])
    validate_error(second, ApiErrorId.ERR_MEDICAL_CLEARANCE_REQUIRED.value, 409)


def test_the_activation_succeeds_only_once_both_masked_rules_are_satisfied(api):
    """Two refusals leave the counter at zero; the third call moves it to one.

    "When no clearance of the required type is issued at all the refusal is
    `ERR_MEDICAL_CLEARANCE_REQUIRED`; when the only issued match has lapsed the
    refusal is `ERR_MEDICAL_CLEARANCE_EXPIRED`."

    Design: Difficulty/priority_pair_validation_conflict/frozen_posture_error_precedes_missing_medical_clearance_error
    """
    bundle = _lookouts_club_frozen_over_an_uncleared_player(api)

    _activate(api, bundle["assignment_id"])
    fixtures.dispose_facility_review(
        api,
        bundle["review_id"],
        "SUBMIT_REMEDIATION",
        bundle["operator_headers"],
        remediation_note="training room rebuilt to TIER_1 spec",
        note="training room rebuilt to TIER_1 spec",
    )
    fixtures.dispose_facility_review(api, bundle["review_id"], "CLOSE")
    _activate(api, bundle["assignment_id"])

    after_refusals = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert after_refusals["active_roster_count"] == 0, (
        f"two refused activations leave the roster empty, got {after_refusals['active_roster_count']}"
    )

    fixtures.issue_clearance(api, bundle["player_id"], "LEVEL_ASSIGNMENT")
    activated = fixtures.dispose_assignment(api, bundle["assignment_id"], "ACTIVATE")
    assert_status(activated, "ACTIVE", "PlayerAssignment")

    affiliate = fixtures.read_affiliate(api, bundle["affiliate_id"])
    assert affiliate["active_roster_count"] == 1, (
        f"the successful activation fills one slot, got {affiliate['active_roster_count']}"
    )
