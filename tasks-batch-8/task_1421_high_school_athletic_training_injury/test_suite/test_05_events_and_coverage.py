"""Event coverage requirements, trainer overlap, coverage lifecycle cascades
(PRD §3.3)."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    api_client,
    assign_coverage,
    create_athlete_as_trainer,
    create_athlete_payload,
    create_coverage_assignment_payload,
    create_event,
    create_injury_for,
    create_supply_item,
    create_venue,
    director_headers,
    get_item,
    make_coach,
    make_director,
    make_nurse,
    make_trainer,
    post_ledger_entry,
    record_baseline,
    record_physical,
    set_clock,
    setup_covered_event,
    setup_venue_with_active_eap,
    trainer_headers,
    validate_error,
    validate_success,
    verify_physical,
)


def _restricted_football_varsity_athlete(trainer, nurse, n):
    """Athlete whose VERIFIED physical outcome is CLEARED_WITH_RESTRICTIONS
    and who holds a CURRENT baseline -> posture CLEARED_WITH_RESTRICTIONS
    via gate 4 (PRD §3.1)."""
    athlete = validate_success(api_client.create_athlete(
        create_athlete_payload(full_name=f"Player P{n}", sex="M",
                               primary_sport="FOOTBALL", team_level="VARSITY",
                               guardian_user_id=f"g-2{n:03d}"),
        trainer_headers(trainer)), expected_status=201)
    ph = record_physical(athlete["id"], trainer,
                         outcome="CLEARED_WITH_RESTRICTIONS",
                         restriction_notes="no contact")
    verify_physical(ph["id"], nurse)
    record_baseline(athlete["id"], trainer)
    return athlete


class TestCoverageRequirementFormula:
    """Difficulty instance coverage_requirement_tiered_modifiers_and_cap."""

    def _setup_restricted_roster(self):
        tr1 = make_trainer()
        nr1 = make_nurse()
        ad = make_director()
        venue = create_venue(venue_name="Stadium")
        for n in range(4):
            _restricted_football_varsity_athlete(tr1, nr1, n)
        return tr1, ad, venue

    def test_tournament_modifiers_hit_cap_of_four(self):
        """PRD §3.3: "Three modifiers then apply, in this order: add one if
        the event is a `TOURNAMENT`; add one if the restricted-roster count —
        athletes whose `primary_sport` and `team_level` match the event and
        whose posture is `CLEARED_WITH_RESTRICTIONS` — is at least four; add
        one if `expected_attendance` is at least one thousand."
        PRD §3.3: "The requirement is the base plus the modifiers, clamped
        so it never falls below one and never exceeds four."

        Design: Difficulty/combinatorial_formula/coverage_requirement_tiered_modifiers_and_cap
        """
        tr1, ad, venue = self._setup_restricted_roster()
        event = create_event(
            ad, event_name="Tourney T", sport="FOOTBALL", team_level="VARSITY",
            event_type="TOURNAMENT", venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T15:00:00Z", expected_attendance=1200)
        # HIGH-contact TOURNAMENT base 2 + tournament 1 + restricted 1
        # + attendance 1 = 5, clamped to the cap of 4.
        assert event["required_trainer_count"] == 4, (
            f"expected the 4-cap, got {event['required_trainer_count']}")

    def test_home_game_same_roster_no_cap(self):
        """PRD §3.3: "The base requirement for a high-contact sport is one
        trainer for a `PRACTICE` and two trainers for a `SCRIMMAGE`,
        `HOME_GAME`, `AWAY_GAME`, or `TOURNAMENT`; medium- and low-contact
        sports need one trainer regardless of event type."

        Design: Difficulty/combinatorial_formula/coverage_requirement_tiered_modifiers_and_cap
        """
        tr1, ad, venue = self._setup_restricted_roster()
        event = create_event(
            ad, event_name="Game G", sport="FOOTBALL", team_level="VARSITY",
            event_type="HOME_GAME", venue_id=venue["id"],
            scheduled_start="2026-08-02T16:00:00Z",
            scheduled_end="2026-08-02T17:00:00Z", expected_attendance=500)
        # HIGH-contact HOME_GAME base 2 + restricted 1 = 3 (no tournament
        # bump, attendance below one thousand).
        assert event["required_trainer_count"] == 3, (
            f"expected base 2 + restricted 1 = 3, got "
            f"{event['required_trainer_count']}")


class TestImmediateConsistency:

    def test_event_create_response_carries_computed_requirement(self):
        """PRD §3.3: "A created event starts in `SCHEDULED` with
        `active_assignment_count` at zero and its `required_trainer_count`
        computed as follows."
        PRD §2.6: "The server recomputes these immediately whenever a
        triggering mutation occurs — recording a physical, declining an
        assignment, appending a ledger entry, approving an order — and during
        the clock sweep of §2.4."

        Design: Corner/consistency_model/immediate_consistency_on_create_and_mutation
        """
        ad = make_director()
        tr1 = make_trainer()
        venue = create_venue(venue_name="Stadium")
        item = create_supply_item()
        set_clock("2026-08-01T12:00:00Z")

        data = validate_success(api_client.create_event(
            {
                "event_name": "Game",
                "sport": "FOOTBALL",
                "team_level": "VARSITY",
                "event_type": "HOME_GAME",
                "venue_id": venue["id"],
                "scheduled_start": "2026-08-02T14:00:00Z",
                "scheduled_end": "2026-08-02T17:00:00Z",
                "expected_attendance": 500,
            },
            director_headers(ad)), expected_status=201)
        # HIGH-contact HOME_GAME base 2, no modifier applies.
        assert data["required_trainer_count"] == 2
        assert data["status"] == "SCHEDULED"

        post_ledger_entry(item["id"], tr1, txn_type="RESTOCK", quantity=5,
                          unit_cost_cents=100,
                          occurred_at="2026-08-01T09:00:00Z")
        item_after = get_item(item["id"])
        assert item_after["current_stock"] == 5, \
            "read-after-write reflects the ledger append immediately"
        assert item_after["stock_status"] == "LOW_STOCK"


class TestStaffRoleMismatch:

    def test_coach_rejected_as_referral_physician_and_coverage_assignee(self):
        """PRD §3.6: "the `physician_staff_id` of the consulting physician —
        which must reference a staff member whose `role_type` is `PHYSICIAN`,
        otherwise `ERR_STAFF_ROLE_MISMATCH`".
        PRD §3.3: "The referenced staff member must carry `role_type`
        `ATHLETIC_TRAINER` and be active; anyone else is rejected with
        `ERR_STAFF_ROLE_MISMATCH`."

        Design: Corner/validations/staff_role_mismatch_on_referral_and_coverage
        """
        coach = make_coach("Coach Cal")
        tr1 = make_trainer()
        ad = make_director()
        venue = create_venue(venue_name="Field")
        athlete = create_athlete_as_trainer(tr1, team_level="JV")
        injury = create_injury_for(athlete["id"], tr1, body_region="KNEE",
                                   mechanism="tackle")
        event = create_event(ad, event_name="Practice", sport="SOCCER",
                             team_level="JV", event_type="PRACTICE",
                             venue_id=venue["id"],
                             scheduled_start="2026-08-02T15:00:00Z",
                             scheduled_end="2026-08-02T16:30:00Z",
                             expected_attendance=0)

        resp = api_client.create_referral(
            {"injury_id": injury["id"], "physician_staff_id": coach["id"],
             "reason": "bad ref", "urgency": "ROUTINE"},
            trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH)

        resp = api_client.create_coverage_assignment(
            create_coverage_assignment_payload(
                event_id=event["id"], staff_id=coach["id"],
                coverage_role="PRIMARY"), director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH)


class TestTrainerPrimaryOverlap:
    """Difficulty instance trainer_primary_overlap_half_open (two tests)."""

    def _setup(self):
        tr1 = make_trainer()
        ad = make_director()
        v1 = create_venue(venue_name="Field 1")
        v2 = create_venue(venue_name="Field 2", surface="TURF")
        v3 = create_venue(venue_name="Field 3", venue_type="INDOOR",
                          surface="COURT")
        ev_a = create_event(ad, event_name="A", sport="FOOTBALL",
                            event_type="HOME_GAME", venue_id=v1["id"],
                            scheduled_start="2026-08-02T14:00:00Z",
                            scheduled_end="2026-08-02T17:00:00Z",
                            expected_attendance=500)
        ev_b = create_event(ad, event_name="B", sport="FOOTBALL",
                            event_type="HOME_GAME", venue_id=v2["id"],
                            scheduled_start="2026-08-02T17:00:00Z",
                            scheduled_end="2026-08-02T19:00:00Z",
                            expected_attendance=500)
        ev_c = create_event(ad, event_name="C", sport="BASKETBALL",
                            event_type="HOME_GAME", venue_id=v3["id"],
                            scheduled_start="2026-08-02T16:00:00Z",
                            scheduled_end="2026-08-02T18:00:00Z",
                            expected_attendance=300)
        assign_coverage(ev_a["id"], tr1["id"], "PRIMARY", ad)
        return tr1, ad, ev_a, ev_b, ev_c

    def test_back_to_back_primary_assignments_do_not_conflict(self):
        """PRD §3.3: "the overlap test treats each window as including its
        start and excluding its end, so back-to-back events where one ends
        exactly as the other begins do not conflict".

        Design: Difficulty/resource_temporal_overlap/trainer_primary_overlap_half_open
        """
        tr1, ad, _, ev_b, _ = self._setup()
        data = validate_success(api_client.create_coverage_assignment(
            create_coverage_assignment_payload(
                event_id=ev_b["id"], staff_id=tr1["id"],
                coverage_role="PRIMARY"), director_headers(ad)),
            expected_status=201)
        assert data["status"] == "ASSIGNED", \
            "half-open adjacency at 17:00 is not a collision"

    def test_one_hour_overlap_rejected_coverage_overlap(self):
        """PRD §3.3: "A trainer may not hold a `PRIMARY` assignment on
        another event whose half-open scheduled window overlaps the new
        event's ... and a violation is rejected with `ERR_COVERAGE_OVERLAP`."

        Design: Difficulty/resource_temporal_overlap/trainer_primary_overlap_half_open
        """
        tr1, ad, _, _, ev_c = self._setup()
        resp = api_client.create_coverage_assignment(
            create_coverage_assignment_payload(
                event_id=ev_c["id"], staff_id=tr1["id"],
                coverage_role="PRIMARY"), director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP)


class TestCoveragePriorityPair:

    def test_temporal_overlap_beats_inactive_staff_reference(self):
        """PRD §2.9: "When several business rules could reject the same
        request, the ordering that decides the surfaced error is: state
        before safety, safety before temporal, temporal before reference
        quality, and all of those before fiscal coverage."
        PRD §3.3: "The referenced staff member must carry `role_type`
        `ATHLETIC_TRAINER` and be active; anyone else is rejected with
        `ERR_STAFF_ROLE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/coverage_assign_temporal_vs_referential_priority
        """
        tr1 = make_trainer()
        ad = make_director()
        v1 = create_venue(venue_name="Stadium")
        v2 = create_venue(venue_name="Gym", venue_type="INDOOR",
                          surface="COURT")
        ev_a = create_event(ad, event_name="Game A", sport="SOCCER",
                            event_type="HOME_GAME", venue_id=v1["id"],
                            scheduled_start="2026-08-02T14:00:00Z",
                            scheduled_end="2026-08-02T17:00:00Z",
                            expected_attendance=100)
        assign_coverage(ev_a["id"], tr1["id"], "PRIMARY", ad)
        # Both violations are now armed: deactivate the trainer...
        validate_success(api_client.patch_staff(
            tr1["id"], {"is_active": False}, ADMIN))
        ev_b = create_event(ad, event_name="Game B", sport="SOCCER",
                            event_type="HOME_GAME", venue_id=v2["id"],
                            scheduled_start="2026-08-02T16:00:00Z",
                            scheduled_end="2026-08-02T18:00:00Z",
                            expected_attendance=100)

        resp = api_client.create_coverage_assignment(
            create_coverage_assignment_payload(
                event_id=ev_b["id"], staff_id=tr1["id"],
                coverage_role="PRIMARY"), director_headers(ad))
        # ...yet the temporal conflict surfaces, not the reference failure.
        validate_error(resp, ApiErrorId.ERR_COVERAGE_OVERLAP)

    def test_inactive_trainer_without_overlap_draws_role_mismatch(self):
        """PRD §3.3: "The referenced staff member must carry `role_type`
        `ATHLETIC_TRAINER` and be active; anyone else is rejected with
        `ERR_STAFF_ROLE_MISMATCH`."

        Design: Difficulty/priority_pair_validation_conflict/coverage_assign_temporal_vs_referential_priority
        """
        tr1 = make_trainer()
        ad = make_director()
        v2 = create_venue(venue_name="Gym", venue_type="INDOOR",
                          surface="COURT")
        ev_b = create_event(ad, event_name="Game B", sport="SOCCER",
                            event_type="HOME_GAME", venue_id=v2["id"],
                            scheduled_start="2026-08-02T16:00:00Z",
                            scheduled_end="2026-08-02T18:00:00Z",
                            expected_attendance=100)
        validate_success(api_client.patch_staff(
            tr1["id"], {"is_active": False}, ADMIN))
        # Isolated single failure: no overlapping PRIMARY assignment exists.
        resp = api_client.create_coverage_assignment(
            create_coverage_assignment_payload(
                event_id=ev_b["id"], staff_id=tr1["id"],
                coverage_role="PRIMARY"), director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_STAFF_ROLE_MISMATCH)


class TestAssignmentLifecycle:

    def test_ownership_then_decline_state_enforcement(self):
        """PRD §3.3: "All three are self-service actions: the caller must be
        the assignment's `staff_id`, otherwise `ERR_OWNERSHIP_MISMATCH`, and
        each requires the stated from-state, otherwise `ERR_INVALID_STATE`."

        Design: Corner/state_machines/coverage_ownership_and_decline_state_rejected
        """
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        ad = make_director()
        venue = create_venue(venue_name="Field")
        event = create_event(ad, event_name="Practice", sport="SOCCER",
                             event_type="PRACTICE", venue_id=venue["id"],
                             scheduled_start="2026-08-02T14:00:00Z",
                             scheduled_end="2026-08-02T15:30:00Z",
                             expected_attendance=0)
        ca = assign_coverage(event["id"], tr1["id"], "PRIMARY", ad)

        # A different trainer is not the assignee.
        resp = api_client.acknowledge_assignment(ca["id"],
                                                 trainer_headers(tr2))
        validate_error(resp, ApiErrorId.ERR_OWNERSHIP_MISMATCH)

        data = validate_success(api_client.acknowledge_assignment(
            ca["id"], trainer_headers(tr1)))
        assert data["status"] == "ACKNOWLEDGED"
        assert data["acknowledged_at"] is not None

        # Decline is defined from ASSIGNED only; ACKNOWLEDGED rejects it.
        resp = api_client.decline_assignment(ca["id"], trainer_headers(tr1))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)

    def test_event_complete_completes_active_assignments(self):
        """PRD §3.3: "A trainer completes an `IN_PROGRESS` event, moving it
        to `COMPLETED`; every assignment of that event in `ON_SITE`,
        `ACKNOWLEDGED`, or `ON_HOLD` moves to `COMPLETED` with it."

        Design: Corner/state_machines/event_complete_completes_active_assignments
        """
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        ad = make_director()
        venue, _ = setup_venue_with_active_eap(tr1, ad)
        event, (ca1, ca2) = setup_covered_event(
            ad, [(tr1, "PRIMARY"), (tr2, "SECONDARY")],
            event_name="Game", sport="FOOTBALL", event_type="HOME_GAME",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T17:00:00Z", expected_attendance=500)
        assert event["status"] == "COVERED"
        validate_success(api_client.acknowledge_assignment(
            ca1["id"], trainer_headers(tr1)))
        validate_success(api_client.check_in_assignment(
            ca1["id"], trainer_headers(tr1)))
        validate_success(api_client.acknowledge_assignment(
            ca2["id"], trainer_headers(tr2)))
        set_clock("2026-08-02T14:05:00Z")
        validate_success(api_client.start_event(event["id"],
                                                trainer_headers(tr1)))

        set_clock("2026-08-02T17:05:00Z")
        completed = validate_success(api_client.complete_event(
            event["id"], trainer_headers(tr1)))
        assert completed["status"] == "COMPLETED"

        ca1_after = validate_success(api_client.get_coverage_assignment(
            ca1["id"], trainer_headers(tr1)))
        ca2_after = validate_success(api_client.get_coverage_assignment(
            ca2["id"], trainer_headers(tr2)))
        assert ca1_after["status"] == "COMPLETED", "ON_SITE cascades down"
        assert ca2_after["status"] == "COMPLETED", "ACKNOWLEDGED cascades"

    def test_event_cancel_spares_terminal_assignments(self):
        """PRD §3.3: "A trainer or the director cancels an event from
        `SCHEDULED`, `COVERED`, or `SUSPENDED_WEATHER` ... moving the event
        to `CANCELLED` and cascading every assignment in `ASSIGNED`,
        `ACKNOWLEDGED`, or `ON_HOLD` to `CANCELLED`."

        Design: Corner/cross_cutting_layers/event_cancel_leaves_terminal_assignments_untouched
        """
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        ad = make_director()
        venue = create_venue(venue_name="Stadium")
        event, (ca1, ca2) = setup_covered_event(
            ad, [(tr1, "PRIMARY"), (tr2, "SECONDARY")],
            event_name="Game", sport="FOOTBALL", event_type="HOME_GAME",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T17:00:00Z", expected_attendance=500)
        declined = validate_success(api_client.decline_assignment(
            ca2["id"], trainer_headers(tr2)))
        assert declined["status"] == "DECLINED"

        cancelled = validate_success(api_client.cancel_event(
            event["id"], trainer_headers(tr1)))
        assert cancelled["status"] == "CANCELLED"

        ca1_after = validate_success(api_client.get_coverage_assignment(
            ca1["id"], trainer_headers(tr1)))
        ca2_after = validate_success(api_client.get_coverage_assignment(
            ca2["id"], trainer_headers(tr2)))
        assert ca1_after["status"] == "CANCELLED", \
            "non-terminal child cascades to CANCELLED"
        assert ca2_after["status"] == "DECLINED", \
            "terminal child is untouched by the cascade"


class TestEventTerminalStateGate:
    """Difficulty instance assignment_gated_by_event_terminal_state."""

    def _setup_cancelled_event(self):
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        ad = make_director()
        venue = create_venue(venue_name="Field")
        event, (ca1,) = setup_covered_event(
            ad, [(tr1, "PRIMARY")],
            event_name="Practice", sport="SOCCER", event_type="PRACTICE",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T15:30:00Z", expected_attendance=0)
        cancelled = validate_success(api_client.cancel_event(
            event["id"], director_headers(ad)))
        return tr1, tr2, ad, cancelled, ca1

    def test_cancel_cascades_open_assignment(self):
        """PRD §3.3: "cascading every assignment in `ASSIGNED`,
        `ACKNOWLEDGED`, or `ON_HOLD` to `CANCELLED`."

        Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_event_terminal_state
        """
        tr1, _, ad, cancelled, ca1 = self._setup_cancelled_event()
        assert cancelled["status"] == "CANCELLED"
        ca1_after = validate_success(api_client.get_coverage_assignment(
            ca1["id"], director_headers(ad)))
        assert ca1_after["status"] == "CANCELLED"

    def test_new_assignment_on_cancelled_event_rejected(self):
        """PRD §3.3: "The event must be in `SCHEDULED` or `COVERED` —
        assigning to an event in any other state is rejected with
        `ERR_INVALID_STATE`."

        Design: Difficulty/cross_entity_state_dependency/assignment_gated_by_event_terminal_state
        """
        _, tr2, ad, cancelled, _ = self._setup_cancelled_event()
        resp = api_client.create_coverage_assignment(
            create_coverage_assignment_payload(
                event_id=cancelled["id"], staff_id=tr2["id"],
                coverage_role="PRIMARY"), director_headers(ad))
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE)


class TestCoverageSlotConservation:
    """Difficulty instance coverage_decline_reassign_conserves_slots."""

    def _setup(self):
        tr1 = make_trainer("Trainer One")
        tr2 = make_trainer("Trainer Two")
        tr3 = make_trainer("Trainer Three")
        ad = make_director()
        venue = create_venue(venue_name="Stadium")
        event, (ca1, ca2) = setup_covered_event(
            ad, [(tr1, "PRIMARY"), (tr2, "SECONDARY")],
            event_name="Game", sport="FOOTBALL", event_type="HOME_GAME",
            venue_id=venue["id"],
            scheduled_start="2026-08-02T14:00:00Z",
            scheduled_end="2026-08-02T17:00:00Z", expected_attendance=500)
        return tr1, tr2, tr3, ad, event, ca2

    def test_decline_drops_event_back_to_scheduled(self):
        """PRD §3.3: "A decline also subtracts one from the event's
        `active_assignment_count`, and if the event was `COVERED` and the
        decrement drops the count below `required_trainer_count`, the event
        bubbles back down from `COVERED` to `SCHEDULED`."
        PRD §3.3: "the per-event coverage view reports `event_id`,
        `required_trainer_count`, `active_assignment_count`, and `is_covered`
        — the last being true exactly when the active count meets the
        requirement."

        Design: Difficulty/compensating_invariant/coverage_decline_reassign_conserves_slots
        """
        tr1, tr2, tr3, ad, event, ca2 = self._setup()
        cov0 = validate_success(api_client.get_event_coverage_status(
            event["id"], director_headers(ad)))
        assert cov0["active_assignment_count"] == 2
        assert cov0["is_covered"] is True

        validate_success(api_client.decline_assignment(
            ca2["id"], trainer_headers(tr2)))
        cov1 = validate_success(api_client.get_event_coverage_status(
            event["id"], director_headers(ad)))
        assert cov1["active_assignment_count"] == 1
        assert cov1["is_covered"] is False
        ev = validate_success(api_client.get_event(event["id"],
                                                   director_headers(ad)))
        assert ev["status"] == "SCHEDULED", \
            "the decline flips the event back below the requirement"

    def test_reassign_restores_covered_slot_count(self):
        """PRD §3.3: "A created assignment starts in `ASSIGNED`, increments
        the event's `active_assignment_count` by one, and when that count
        reaches `required_trainer_count` the event bubbles up from
        `SCHEDULED` to `COVERED` on its own."

        Design: Difficulty/compensating_invariant/coverage_decline_reassign_conserves_slots
        """
        tr1, tr2, tr3, ad, event, ca2 = self._setup()
        validate_success(api_client.decline_assignment(
            ca2["id"], trainer_headers(tr2)))
        assign_coverage(event["id"], tr3["id"], "SECONDARY", ad)
        cov2 = validate_success(api_client.get_event_coverage_status(
            event["id"], director_headers(ad)))
        assert cov2["active_assignment_count"] == 2
        assert cov2["is_covered"] is True, \
            "decline+reassign conserves the event's covered slot count"
        ev = validate_success(api_client.get_event(event["id"],
                                                   director_headers(ad)))
        assert ev["status"] == "COVERED"
