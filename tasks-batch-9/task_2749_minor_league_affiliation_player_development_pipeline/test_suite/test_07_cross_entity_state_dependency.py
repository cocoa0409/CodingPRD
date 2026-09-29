"""Operations whose legality is decided by the status of a *different* row:
the club's licence in one direction, a sibling rehab assignment in the other.
"""

from test_helpers import (
    FARM_DIRECTOR_HEADERS,
    MEDICAL_DIRECTOR_HEADERS,
    ApiClient,
    ApiErrorId,
    assert_integer,
    assert_status,
    factories,
    fixtures,
    validate_error,
    validate_success,
)


def _activate_assignment(api: ApiClient, assignment_id: str):
    """Raw ACTIVATE call, so a refusal can be inspected rather than raised."""
    return api.dispose_assignment(
        assignment_id, factories.disposition_payload("ACTIVATE"), FARM_DIRECTOR_HEADERS
    )


def _issue_clearance(api: ApiClient, clearance_id: str, ceiling=25.00):
    """Raw ISSUE call, so a refusal can be inspected rather than raised."""
    return api.dispose_medical_clearance(
        clearance_id,
        factories.clearance_issue_payload(
            cleared_workload_ceiling_index=ceiling, expires_on="2026-12-31"
        ),
        MEDICAL_DIRECTOR_HEADERS,
    )


# ---------------------------------------------------------------------------
# Instance 1 — the activation reads the parent licence's status
# ---------------------------------------------------------------------------


def _aviators_club_with_a_suspended_licence(api: ApiClient) -> dict:
    """A cleared player pending at a club whose licence has been suspended."""
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Las Vegas Aviators",
            "level": "TRIPLE_A",
            "market_city": "Las Vegas",
            "meal_stipend_cents_per_day": 3400,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_1",
            "club_reimbursement_cap_cents": 900000,
            "minimum_active_players": 0,
        },
    )
    pending = fixtures.pending_assignment(
        api,
        club["affiliate_id"],
        player_overrides={
            "full_name": "Cormac Vidal",
            "origin": "DOMESTIC_DRAFT",
            "signed_date": "2024-06-10",
            "service_days_accrued": 200,
        },
        effective_date="2026-08-05",
        end_date="2026-09-30",
    )
    club.update(pending)
    club["suspended_agreement"] = fixtures.dispose_agreement(
        api, club["agreement_id"], "SUSPEND", note="facility audit pending"
    )
    return club


def test_a_suspended_licence_blocks_the_activation_with_the_status_error(api: ApiClient):
    """A pending assignment survives the suspension but cannot be activated.

    PRD 3.2: "Suspending an `ACTIVE` licence moves it `ACTIVE` → `SUSPENDED`,
    sets `posture` to `FROZEN`, and cascades to the club's players: every
    assignment at that affiliate currently in status `ACTIVE` moves to
    `SUSPENDED`, while assignments in `PENDING_CLEARANCE`, `COMPLETED` or
    `REVOKED` are left untouched."  PRD 2.6 then orders the two licence gates:
    "The affiliate receiving the operation has an agreement in status `ACTIVE`,
    otherwise `ERR_AGREEMENT_NOT_ACTIVE` (409)." is checked before "That
    agreement's `posture` is not `FROZEN`, otherwise
    `ERR_AGREEMENT_POSTURE_FROZEN` (409)." so the status error is the one that
    surfaces even though the posture is `FROZEN` too.

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_agreement_active_on_the_affiliate
    """
    club = _aviators_club_with_a_suspended_licence(api)

    suspended = club["suspended_agreement"]
    assert_status(suspended, "SUSPENDED", "AffiliationAgreement")
    assert suspended["posture"] == "FROZEN", (
        f"a suspended licence must sit at FROZEN posture, got {suspended['posture']}"
    )
    assert_status(
        fixtures.read_assignment(api, club["assignment_id"]),
        "PENDING_CLEARANCE",
        "PlayerAssignment",
    )

    refused = _activate_assignment(api, club["assignment_id"])
    validate_error(refused, ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value, 409)

    assert_status(
        fixtures.read_assignment(api, club["assignment_id"]),
        "PENDING_CLEARANCE",
        "PlayerAssignment",
    )
    affiliate = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(affiliate["active_roster_count"], 0, "active_roster_count")
    player = fixtures.read_player(api, club["player_id"])
    assert_integer(player["option_years_used"], 0, "option_years_used")


def test_reinstating_the_licence_lets_the_identical_activation_through(api: ApiClient):
    """Only the parent's status changed, and the same call now succeeds.

    PRD 3.2: "Reinstating a `SUSPENDED` licence moves it `SUSPENDED` →
    `ACTIVE` and, like the original activation, requires the affiliate's
    `facility_status` not to be `DEFICIENT`, failing which the reinstatement is
    refused with `ERR_FACILITY_DEFICIENCY_BLOCKING`; reinstatement re-runs the
    posture derivation and writes `posture` to `OPEN` or `RESTRICTED`."  With
    the licence back at `ACTIVE` and `OPEN`, the byte-identical activation that
    was refused a moment ago is accepted, proving nothing about the assignment
    itself was ever at fault.

    Design: Difficulty/cross_entity_state_dependency/assignment_activation_requires_agreement_active_on_the_affiliate
    """
    club = _aviators_club_with_a_suspended_licence(api)
    validate_error(
        _activate_assignment(api, club["assignment_id"]),
        ApiErrorId.ERR_AGREEMENT_NOT_ACTIVE.value,
        409,
    )

    reinstated = fixtures.dispose_agreement(api, club["agreement_id"], "REINSTATE")
    assert_status(reinstated, "ACTIVE", "AffiliationAgreement")
    assert reinstated["posture"] == "OPEN", (
        f"a reinstated licence with no deficiency and no floor must be OPEN, "
        f"got {reinstated['posture']}"
    )

    activated = validate_success(_activate_assignment(api, club["assignment_id"]), 200)
    assert_status(activated, "ACTIVE", "PlayerAssignment")

    affiliate = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(affiliate["active_roster_count"], 1, "active_roster_count")
    player = fixtures.read_player(api, club["player_id"])
    assert_integer(player["option_years_used"], 1, "option_years_used")


# ---------------------------------------------------------------------------
# Instance 2 — the clearance reads a sibling assignment, and only for one type
# ---------------------------------------------------------------------------


def _complex_club_with_a_requested_rehab_complete(api: ApiClient) -> dict:
    """A player holding no assignment at all and a `REQUESTED` completion."""
    club = fixtures.licensed_affiliate(
        api,
        affiliate_overrides={
            "name": "Arizona Complex Club",
            "level": "COMPLEX",
            "market_city": "Mesa",
            "meal_stipend_cents_per_day": 2500,
        },
        agreement_overrides={
            "facility_standard_tier": "TIER_3",
            "club_reimbursement_cap_cents": 400000,
            "minimum_active_players": 0,
        },
    )
    player = fixtures.create_player(
        api,
        full_name="Nikolai Braun",
        origin="DOMESTIC_DRAFT",
        signed_date="2024-06-10",
        service_days_accrued=210,
    )
    completion = fixtures.request_clearance(api, player["id"], "REHAB_COMPLETE")
    club["player_id"] = player["id"]
    club["completion_id"] = completion["id"]
    return club


def test_issuing_a_completion_clearance_without_a_rehab_assignment_is_refused(api: ApiClient):
    """The gate fires on `REHAB_COMPLETE` alone, not on every clearance type.

    PRD 3.5: "For a `REHAB_COMPLETE` clearance there is an additional
    precondition: the player must already hold an assignment of type `REHAB` in
    status `ACTIVE`, failing which the issue is refused with
    `ERR_REHAB_ASSIGNMENT_REQUIRED`."  The refused record stays `REQUESTED`, and
    a `REHAB_START` clearance for the same player with no assignment anywhere in
    the system issues without objection, which shows the precondition is
    conditional on `clearance_type` rather than universal.

    Design: Difficulty/cross_entity_state_dependency/rehab_complete_clearance_issue_requires_active_rehab_assignment
    """
    club = _complex_club_with_a_requested_rehab_complete(api)

    refused = _issue_clearance(api, club["completion_id"])
    validate_error(refused, ApiErrorId.ERR_REHAB_ASSIGNMENT_REQUIRED.value, 409)
    assert_status(
        fixtures.read_clearance(api, club["player_id"], club["completion_id"]),
        "REQUESTED",
        "MedicalClearance",
    )

    start = fixtures.request_clearance(api, club["player_id"], "REHAB_START")
    issued_start = validate_success(_issue_clearance(api, start["id"], ceiling=8.00), 200)
    assert_status(issued_start, "ISSUED", "MedicalClearance")
    assert issued_start["clearance_type"] == "REHAB_START", (
        f"expected the REHAB_START record back, got {issued_start['clearance_type']}"
    )


def test_an_active_rehab_assignment_unlocks_the_identical_completion_issue(api: ApiClient):
    """The rehab assignment satisfies the gate without touching the roster.

    PRD 3.6: "for a `REHAB` assignment the club's `rehab_assignment_count` must
    be strictly below the organization's rehab slot allowance of three
    concurrent rehab assignments per club (`ERR_REHAB_SLOT_LIMIT_EXCEEDED`)."
    PRD 3.3 keeps the two tallies apart: "`active_roster_count` is the number of
    assignments at the club with status `ACTIVE` and type `LEVEL` or `COMPLEX`.
    `rehab_assignment_count` is the number at the club with status `ACTIVE` and
    type `REHAB`."  So the activation that unblocks the completion clearance
    charges no option year and occupies no roster slot.

    Design: Difficulty/cross_entity_state_dependency/rehab_complete_clearance_issue_requires_active_rehab_assignment
    """
    club = _complex_club_with_a_requested_rehab_complete(api)
    validate_error(
        _issue_clearance(api, club["completion_id"]),
        ApiErrorId.ERR_REHAB_ASSIGNMENT_REQUIRED.value,
        409,
    )
    start = fixtures.request_clearance(api, club["player_id"], "REHAB_START")
    validate_success(_issue_clearance(api, start["id"], ceiling=8.00), 200)

    rehab = fixtures.create_assignment(
        api,
        club["player_id"],
        club["affiliate_id"],
        assignment_type="REHAB",
        movement_reason="REHAB_START",
        effective_date="2026-08-05",
        end_date="2026-09-15",
    )
    activated = validate_success(_activate_assignment(api, rehab["id"]), 200)
    assert_status(activated, "ACTIVE", "PlayerAssignment")
    assert activated["assignment_type"] == "REHAB", (
        f"expected a REHAB assignment, got {activated['assignment_type']}"
    )

    issued = validate_success(_issue_clearance(api, club["completion_id"]), 200)
    assert_status(issued, "ISSUED", "MedicalClearance")

    affiliate = fixtures.read_affiliate(api, club["affiliate_id"])
    assert_integer(affiliate["rehab_assignment_count"], 1, "rehab_assignment_count")
    assert_integer(affiliate["active_roster_count"], 0, "active_roster_count")

    player = fixtures.read_player(api, club["player_id"])
    assert_integer(player["option_years_used"], 0, "option_years_used")
    assert player["roster_status"] == "RESERVE_LIST", (
        f"a rehab activation must leave roster standing at RESERVE_LIST, "
        f"got {player['roster_status']}"
    )
