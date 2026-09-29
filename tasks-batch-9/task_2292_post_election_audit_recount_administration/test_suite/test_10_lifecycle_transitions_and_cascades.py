"""Lifecycle transitions: valid ladders, refused triggers, terminal lockdown and cascades."""

import pytest

from test_helpers import (
    ApiErrorId,
    api_client,
    assertions,
    constants,
    factories,
    fixtures,
    make_candidate_representative_headers,
    make_canvassing_board_member_headers,
    make_tally_team_lead_headers,
    validate_error,
    validate_paginated,
    validate_success,
)
from test_helpers.test_users import TEST_USERS

DIRECTOR = TEST_USERS["elections_director_headers"]
AUDIT_MANAGER = TEST_USERS["audit_manager_headers"]
CUSTODY_OFFICER = TEST_USERS["custody_officer_headers"]

BOARD_ONE = constants.TEST_DEFAULTS["BOARD_DEM_USER_ID"]
BOARD_TWO = constants.TEST_DEFAULTS["BOARD_REP_USER_ID"]
BOARD_THREE = constants.TEST_DEFAULTS["BOARD_DEM_2_USER_ID"]
CANVASS_DAY = constants.TEST_DEFAULTS["CLOCK_CANVASS_DAY"]
AUDIT_SEED = constants.TEST_DEFAULTS["AUDIT_SEED"]

SIX_VOTE_OVERSTATEMENT = {"ALVAREZ": 522, "BRENNAN": 478}


def _setup_open_equipment_action():
    """A documented finding on a 522/478 count carrying one OPEN EQUIPMENT action."""
    scenario = fixtures.setup_open_discrepancy(counted_votes=SIX_VOTE_OVERSTATEMENT)
    scenario["discrepancy"] = fixtures.document_discrepancy(
        scenario["discrepancy"]["id"],
        "Scanner 3 mis-read a folded corner on 6 ballots.",
        BOARD_ONE,
    )
    scenario["action"] = fixtures.create_corrective_action(
        scenario["discrepancy"]["id"],
        category="EQUIPMENT",
        description="Recalibrate scanner 3 and re-run the test deck.",
    )
    return scenario


class TestCorrectiveActionLadder:
    """Three forward triggers, three stamps, one version per write."""

    def test_the_action_walks_open_to_verified_stamping_only_its_own_fields(self):
        """PRD §3.6: "`IN_PROGRESS` may become `COMPLETED`, which stamps
        `completed_by_user_id` from the acting member's identity and `completed_at` from the
        clock. `COMPLETED` may become `VERIFIED`, which requires that the acting member's
        identity differ from `completed_by_user_id` ... and which stamps `verified_by_user_id`
        and `verified_at`." §3.6: "Every transition increments the action's `version` by one."

        Design: Corner/state_machines/corrective_action_ladder_open_in_progress_completed_verified
        """
        scenario = _setup_open_equipment_action()
        action = scenario["action"]
        assertions.assert_corrective_action(action)
        assert action["status"] == "OPEN"
        assert action["completed_by_user_id"] is None
        assert action["verified_by_user_id"] is None

        in_progress = fixtures.transition_corrective_action(
            action["id"], "IN_PROGRESS", BOARD_ONE
        )
        completed = fixtures.transition_corrective_action(
            action["id"], "COMPLETED", BOARD_ONE, note="Calibration run 2026-11-05"
        )
        verified = fixtures.transition_corrective_action(
            action["id"], "VERIFIED", BOARD_TWO, note="Test deck matches"
        )

        assert in_progress["status"] == "IN_PROGRESS"
        assert completed["status"] == "COMPLETED"
        assert verified["status"] == "VERIFIED"
        assert verified["completed_by_user_id"] == BOARD_ONE
        assertions.assert_same_instant(
            verified["completed_at"], CANVASS_DAY, "completed_at"
        )
        assert verified["verified_by_user_id"] == BOARD_TWO
        assertions.assert_same_instant(
            verified["verified_at"], CANVASS_DAY, "verified_at"
        )
        assert verified["version"] == 4
        assert (
            fixtures.read_discrepancy(scenario["discrepancy"]["id"])["status"]
            == "DOCUMENTED"
        )


class TestCorrectiveActionIllegalTransitions:
    """`to_status` is checked against the transitions that exist, not against the enum."""

    def test_a_skipped_step_and_a_move_out_of_cancelled_are_both_refused(self):
        """PRD §3.6: "And an action in `OPEN` or `IN_PROGRESS` may become `CANCELLED`.
        `VERIFIED` and `CANCELLED` are both terminal, and any other requested `to_status` from
        the action's current state is an illegal corrective-action transition."

        Design: Corner/state_machines/corrective_action_cannot_skip_to_verified_or_leave_cancelled
        """
        scenario = _setup_open_equipment_action()
        action_id = scenario["action"]["id"]

        skipped = api_client.transition_corrective_action(
            action_id, {"to_status": "VERIFIED"}, make_canvassing_board_member_headers(BOARD_TWO)
        )
        cancelled = fixtures.transition_corrective_action(
            action_id, "CANCELLED", BOARD_ONE, note="Scanner retired"
        )
        after_terminal = api_client.transition_corrective_action(
            action_id,
            {"to_status": "IN_PROGRESS"},
            make_canvassing_board_member_headers(BOARD_ONE),
        )

        validate_error(
            skipped, ApiErrorId.ERR_INVALID_CORRECTIVE_ACTION_STATE.value, 409
        )
        assert cancelled["status"] == "CANCELLED"
        assert cancelled["completed_by_user_id"] is None
        validate_error(
            after_terminal, ApiErrorId.ERR_INVALID_CORRECTIVE_ACTION_STATE.value, 409
        )
        final = fixtures.read_corrective_action(action_id)
        assert final["status"] == "CANCELLED"
        assert final["version"] == 2


class TestRetrievalAuthorizationIsRevokedByTermination:
    """Standing the audit down closes the vault door again."""

    def test_a_check_out_after_termination_is_refused_as_unauthorized(self):
        """PRD §3.4: "retrieval authorization is revoked — for every drawn batch of this audit
        still in `PENDING_RETRIEVAL`, the underlying physical batch's
        `retrieval_authorized_at` is set back to null". §2.9: "The batch's
        `retrieval_authorized_at` is set — otherwise `ERR_RETRIEVAL_NOT_AUTHORIZED`."

        Design: Corner/state_machines/retrieve_after_audit_terminate_returns_retrieval_not_authorized
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        terminated = fixtures.terminate_audit(
            scenario["audit"]["id"], "Audit stood down before any retrieval."
        )
        physical = fixtures.read_batch(drawn["ballot_batch_id"])

        response = api_client.retrieve_audit_batch(
            drawn["id"],
            factories.retrieve_audit_batch_payload(
                physical["version"], physical["current_seal_number"]
            ),
            CUSTODY_OFFICER,
        )

        assert terminated["status"] == "TERMINATED"
        validate_error(response, ApiErrorId.ERR_RETRIEVAL_NOT_AUTHORIZED.value, 409)
        batch = fixtures.read_batch(physical["id"])
        assert batch["retrieval_authorized_at"] is None
        assert batch["custody_status"] == "SEALED"
        assert batch["open_checkout_count"] == 0
        assert fixtures.read_audit_batch(drawn["id"])["retrieval_status"] == (
            "PENDING_RETRIEVAL"
        )
        _rows, meta = validate_paginated(
            api_client.list_ballot_batch_custody_events(
                physical["id"], CUSTODY_OFFICER, params={"limit": 10}
            )
        )
        assert meta["total_count"] == 2


class TestRetrievalSideEffects:
    """One check-out writes three rows and one custody entry."""

    def test_a_single_retrieve_moves_both_batch_rows_and_appends_the_check_out(self):
        """PRD §3.2: "On success the physical batch's `custody_status` becomes `CHECKED_OUT`,
        `last_checked_out_at` is stamped from the clock, `open_checkout_count` increases by
        one, a `CHECK_OUT` custody entry is appended whose `seal_number_before` is the seal
        just verified and whose `seal_number_after` is null ... the drawn batch's
        `retrieval_status` moves from `PENDING_RETRIEVAL` to `RETRIEVED`, and the physical
        batch's `version` is incremented by one."

        Design: Corner/state_machines/retrieve_side_effects_span_three_entities_and_the_custody_log
        """
        scenario = fixtures.setup_canvassed_contest()
        scenario.update(fixtures.setup_audit_round_one(scenario["contest"]["id"]))
        drawn = scenario["audit_batches"][0]
        other_drawn = scenario["audit_batches"][1]
        physical = fixtures.read_batch(drawn["ballot_batch_id"])
        assert physical["version"] == 2

        retrieved = validate_success(
            api_client.retrieve_audit_batch(
                drawn["id"],
                factories.retrieve_audit_batch_payload(
                    physical["version"],
                    physical["current_seal_number"],
                    note="Escorted to ROOM-A",
                ),
                CUSTODY_OFFICER,
            )
        )

        assertions.assert_audit_batch(retrieved)
        assert retrieved["retrieval_status"] == "RETRIEVED"
        assert retrieved["version"] == 2
        assert retrieved["tally_status"] == "NOT_STARTED"
        batch = fixtures.read_batch(physical["id"])
        assert batch["custody_status"] == "CHECKED_OUT"
        assertions.assert_same_instant(
            batch["last_checked_out_at"], CANVASS_DAY, "last_checked_out_at"
        )
        assert batch["open_checkout_count"] == 1
        assert batch["checkout_cycle_count"] == 0
        assert batch["last_resealed_at"] is None
        assert batch["current_seal_number"] == physical["current_seal_number"]
        assert batch["version"] == 3
        events = fixtures.list_custody_events(physical["id"])
        assert len(events) == 3
        check_out = events[2]
        assert check_out["sequence_no"] == 3
        assert check_out["event_type"] == "CHECK_OUT"
        assert check_out["seal_number_before"] == physical["current_seal_number"]
        assert check_out["seal_number_after"] is None
        assert check_out["note"] == "Escorted to ROOM-A"
        assert check_out["actor_role"] == "CustodyOfficer"
        assert fixtures.read_audit_batch(other_drawn["id"])["retrieval_status"] == (
            "PENDING_RETRIEVAL"
        )
        assert fixtures.read_batch(other_drawn["ballot_batch_id"])[
            "custody_status"
        ] == "SEALED"


class TestTriggersAbsentFromTheCurrentState:
    """Three entities, three refusals, three untouched rows."""

    def test_closing_canvassing_and_reopening_out_of_turn_each_report_their_own_code(self):
        """PRD §2.9: "The entity addressed by the path is in a state from which the requested
        transition exists ... otherwise the matching invalid-state error:
        `ERR_INVALID_ELECTION_STATE`, `ERR_INVALID_CONTEST_STATE` ...
        `ERR_INVALID_AUDIT_STATE` ... `ERR_INVALID_TALLY_STATE`". §3.4: "Closing is available
        from `TALLYING`, from `DISCREPANCY_REVIEW` and from `ESCALATED_FULL_HAND_COUNT`."

        Design: Corner/state_machines/invalid_trigger_family_close_canvass_reopen_are_each_refused
        """
        scenario = fixtures.setup_draft_tally()
        planned = validate_success(
            api_client.create_audit(
                {
                    "contest_id": scenario["contest"]["id"],
                    "audit_type": "FIXED_PERCENTAGE",
                    "fixed_percentage_pct": 5,
                },
                AUDIT_MANAGER,
            ),
            201,
        )
        assert planned["status"] == "PLANNED"

        close = api_client.close_audit(planned["id"], AUDIT_MANAGER)
        canvass = api_client.submit_canvass_results(
            scenario["contest"]["id"],
            {"reported_votes": {"ALVAREZ": 3160, "BRENNAN": 2840}},
            DIRECTOR,
        )
        reopen = api_client.reopen_manual_tally(
            scenario["manual_tally"]["id"],
            {"reason": "Recount the stack"},
            make_tally_team_lead_headers(scenario["team"]["id"]),
        )

        validate_error(close, ApiErrorId.ERR_INVALID_AUDIT_STATE.value, 409)
        assert fixtures.read_audit(planned["id"])["status"] == "PLANNED"
        validate_error(canvass, ApiErrorId.ERR_INVALID_CONTEST_STATE.value, 409)
        contest = fixtures.read_contest(scenario["contest"]["id"])
        assert contest["reported_votes"] == {"ALVAREZ": 3150, "BRENNAN": 2850}
        assert contest["margin_votes"] == 300
        assert contest["version"] == 2
        validate_error(reopen, ApiErrorId.ERR_INVALID_TALLY_STATE.value, 409)
        tally = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert tally["status"] == "DRAFT"
        assert tally["reopen_count"] == 0
        assert tally["version"] == 1


class TestRecountInitialState:
    """The deposit is priced at filing, and nothing else has happened yet."""

    def test_a_filed_recount_is_requested_with_every_money_field_at_zero(self):
        """PRD §3.8: "A filed recount is `REQUESTED` with `deposit_paid_cents`,
        `refunded_cents`, `forfeited_cents`, `admin_retained_cents` and `actual_cost_cents` all
        zero, `refund_variant` `NONE`, `team_hours`, `final_votes`, `final_margin_votes`,
        `margin_change_votes` and `denial_reason` null, and `outcome_changed` false." §3.8: "A
        `CANDIDATE_REQUESTED` recount is priced as the filing fee of 50000 cents plus the
        applicable rate multiplied by `ballots_in_scope`, then clamped ... and `deposit_status`
        is `PENDING`."

        Design: Corner/state_machines/recount_initial_state_is_requested_with_deposit_pending
        """
        scenario = fixtures.setup_canvassed_contest()
        contest = fixtures.read_contest(scenario["contest"]["id"])

        response = api_client.create_recount(
            factories.create_recount_payload(
                contest["id"],
                contest["version"],
                requested_by_candidate_name="BRENNAN",
            ),
            make_candidate_representative_headers("u-cand-1"),
        )

        recount = validate_success(response, 201)
        assertions.assert_recount(recount)
        assert recount["status"] == "REQUESTED"
        assert recount["deposit_status"] == "PENDING"
        assert recount["ballots_in_scope"] == 6000
        assert recount["required_deposit_cents"] == 200000
        assert recount["deposit_paid_cents"] == 0
        assert recount["refunded_cents"] == 0
        assert recount["forfeited_cents"] == 0
        assert recount["admin_retained_cents"] == 0
        assert recount["actual_cost_cents"] == 0
        assert recount["refund_variant"] == "NONE"
        assert recount["final_votes"] is None
        assert recount["final_margin_votes"] is None
        assert recount["margin_change_votes"] is None
        assert recount["outcome_changed"] is False
        assert recount["requested_by_user_id"] == "u-cand-1"
        assert recount["scope_batch_ids"] is None
        assert recount["version"] == 1
        assert fixtures.read_contest(contest["id"])["open_recount_count"] == 1


class TestTerminalLockdown:
    """`REVOKED` and `DISBANDED` have no outgoing transitions at all."""

    def test_a_second_revoke_a_second_disband_and_a_late_roster_are_refused(self):
        """PRD §3.5: "`DISBANDED` is terminal, and disbanding an already disbanded team is an
        illegal team transition." §3.5: "Adding members to a `DISBANDED` team is an illegal
        team transition." §3.9: "Revocation sets `status` to `REVOKED`, which is terminal".

        Design: Corner/state_machines/terminal_lockdown_revoked_credential_and_disbanded_team_refuse_every_trigger
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election()
        fixtures.create_contest(election["id"])
        team = fixtures.create_bipartisan_team(election["id"])
        disbanded = validate_success(
            api_client.disband_tally_team(team["id"], DIRECTOR)
        )
        credential = fixtures.create_observer_credential(election["id"])
        revoked = validate_success(
            api_client.revoke_observer_credential(
                credential["id"], {"revoked_reason": "Credential lost"}, DIRECTOR
            )
        )
        assert disbanded["version"] == 3
        assert revoked["version"] == 2

        second_revoke = api_client.revoke_observer_credential(
            credential["id"], {"revoked_reason": "Duplicate revocation"}, DIRECTOR
        )
        second_disband = api_client.disband_tally_team(team["id"], DIRECTOR)
        late_roster = api_client.set_tally_team_members(
            team["id"],
            {"members": [{"user_id": "u-dem-9", "party": "DEM", "seat_role": "LEAD"}]},
            DIRECTOR,
        )

        validate_error(
            second_revoke, ApiErrorId.ERR_INVALID_CREDENTIAL_STATE.value, 409
        )
        validate_error(second_disband, ApiErrorId.ERR_INVALID_TEAM_STATE.value, 409)
        validate_error(late_roster, ApiErrorId.ERR_INVALID_TEAM_STATE.value, 409)
        final_credential = fixtures.read_observer_credential(credential["id"])
        assertions.assert_observer_credential(final_credential)
        assert final_credential["status"] == "REVOKED"
        assert final_credential["revoked_reason"] == "Credential lost"
        assert final_credential["version"] == 2
        final_team = fixtures.read_tally_team(team["id"])
        assertions.assert_tally_team(final_team)
        assert final_team["status"] == "DISBANDED"
        assert len(final_team["members"]) == 2
        assert final_team["version"] == 3


class TestRepeatedTriggersAreErrorsNotReplays:
    """Re-issuing a trigger that already fired never silently succeeds."""

    def test_a_second_seed_and_a_second_document_leave_the_first_ones_standing(self):
        """PRD §3.4: "The audit must be `PLANNED` — a second ceremony on the same audit is an
        illegal transition". §3.6: "The canvassing board documents it with a
        `documentation_note`, moving it to `DOCUMENTED`".

        Design: Corner/state_machines/repeat_seed_and_repeat_document_are_rejected_not_replayed
        """
        scenario = fixtures.setup_open_discrepancy(counted_votes=SIX_VOTE_OVERSTATEMENT)
        documented = fixtures.document_discrepancy(
            scenario["discrepancy"]["id"],
            "Scanner 3 mis-read a folded corner on 6 ballots.",
            BOARD_ONE,
        )
        assert documented["version"] == 2

        second_seed = api_client.seed_audit(
            scenario["audit"]["id"], {"random_seed": AUDIT_SEED}, AUDIT_MANAGER
        )
        second_document = api_client.document_discrepancy(
            documented["id"],
            {"documentation_note": "Second look at the same stack."},
            make_canvassing_board_member_headers(BOARD_TWO),
        )

        validate_error(second_seed, ApiErrorId.ERR_INVALID_AUDIT_STATE.value, 409)
        validate_error(
            second_document, ApiErrorId.ERR_INVALID_DISCREPANCY_STATE.value, 409
        )
        audit = fixtures.read_audit(scenario["audit"]["id"])
        assert audit["random_seed"] == AUDIT_SEED
        assertions.assert_same_instant(
            audit["seed_published_at"], CANVASS_DAY, "seed_published_at"
        )
        assert audit["status"] == "DISCREPANCY_REVIEW"
        finding = fixtures.read_discrepancy(documented["id"])
        assertions.assert_discrepancy(finding)
        assert finding["status"] == "DOCUMENTED"
        assert finding["documentation_note"] == (
            "Scanner 3 mis-read a folded corner on 6 ballots."
        )
        assert finding["version"] == 2


class TestCertificationCascadeAndFreeze:
    """The parent's terminal state reaches every child and then freezes the election."""

    def test_certifying_pushes_certified_down_and_refuses_every_later_write(self):
        """PRD §3.1: "On success the election's `status` becomes `CERTIFIED`, `certified_at`
        is stamped from the clock, every contest of the election moves from `CANVASSED` to
        `CERTIFIED` (each contest's `version` incrementing by one), `certification_risk_flag`
        is set to false, `contest_window_ends_at` is re-derived as ten days after
        `effective_certification_deadline_at`, and the election's `version` is incremented by
        one." §2.9: "Every other write of a `CERTIFIED` election is refused with
        `ERR_ELECTION_ALREADY_CERTIFIED`: no new contests, ballot batches (single or bulk),
        audits, recounts or hand tallies".

        Design: Corner/state_machines/certify_cascades_every_contest_and_freezes_further_writes
        """
        scenario = fixtures.setup_canvassed_contest()
        contest_id = scenario["contest"]["id"]

        certified = validate_success(
            api_client.certify_election(scenario["election"]["id"], DIRECTOR)
        )
        frozen = api_client.create_audit(
            factories.create_audit_payload(contest_id), AUDIT_MANAGER
        )
        again = api_client.certify_election(scenario["election"]["id"], DIRECTOR)

        assertions.assert_election(certified)
        assert certified["status"] == "CERTIFIED"
        assertions.assert_same_instant(
            certified["certified_at"], CANVASS_DAY, "certified_at"
        )
        assert certified["version"] == 3
        assertions.assert_same_instant(
            certified["contest_window_ends_at"],
            "2026-12-04T17:00:00Z",
            "contest_window_ends_at",
        )
        assert certified["certification_risk_flag"] is False
        contest = fixtures.read_contest(contest_id)
        assert contest["status"] == "CERTIFIED"
        assert contest["version"] == 3
        validate_error(frozen, ApiErrorId.ERR_ELECTION_ALREADY_CERTIFIED.value, 409)
        _audits, audit_meta = validate_paginated(
            api_client.list_audits(AUDIT_MANAGER, params={"limit": 100})
        )
        assert audit_meta["total_count"] == 0
        validate_error(again, ApiErrorId.ERR_INVALID_ELECTION_STATE.value, 409)
        assert fixtures.read_election(scenario["election"]["id"])["version"] == 3


class TestElectionCanvassBubblesUpOnTheLastContest:
    """The parent moves on the last child, never on the first."""

    def test_the_election_stays_open_until_its_second_contest_canvasses(self):
        """PRD §3.1: "when every contest of the election has reached `CANVASSED` and at least
        one contest exists, the election moves from `OPEN` to `CANVASSED`, its
        `timeline_status` and `certification_risk_flag` are recomputed, and its `version` is
        incremented by one. The election's own move to `CANVASSED` is never requested
        directly; it is only ever the consequence of the last contest being canvassed."

        Design: Corner/state_machines/election_canvasses_only_when_the_last_contest_canvasses
        """
        fixtures.set_clock(CANVASS_DAY)
        election = fixtures.create_election()
        first = fixtures.create_contest(election["id"])
        second = fixtures.create_contest(
            election["id"],
            contest_label="C2",
            office_name="State Treasurer",
            candidate_names=["CHEN", "DAVIS"],
            ballots_cast=3000,
        )
        fixtures.canvass_contest(first["id"])
        midway = fixtures.read_election(election["id"])

        last = fixtures.canvass_contest(
            second["id"], reported_votes={"CHEN": 1575, "DAVIS": 1425}
        )

        assert midway["status"] == "OPEN"
        assert midway["version"] == 1
        assert last["version"] == 2
        assert last["status"] == "CANVASSED"
        assert last["margin_votes"] == 150
        assert last["margin_pct"] == pytest.approx(5.0000, abs=0.00005)
        final_election = fixtures.read_election(election["id"])
        assert final_election["status"] == "CANVASSED"
        assert final_election["version"] == 2
        assert final_election["timeline_status"] == "ON_TRACK"
        assert final_election["certification_risk_flag"] is False
        first_contest = fixtures.read_contest(first["id"])
        assert first_contest["status"] == "CANVASSED"
        assert first_contest["version"] == 2


class TestQuarantineVoidsTheDraftCount:
    """Sealing the evidence away reaches across into the audit."""

    def test_quarantining_the_container_voids_the_draft_tally_and_its_drawing(self):
        """PRD §3.2: "The transition appends a `QUARANTINE` custody entry, then reaches across
        the custody boundary into the audit: every hand tally still in `DRAFT` whose drawn
        batch references this physical batch moves from `DRAFT` to `VOIDED`, and then every
        drawn batch referencing this physical batch whose `tally_status` is `NOT_STARTED` or
        `IN_PROGRESS` has its `tally_status` set to `VOIDED`." §3.2: "When the quarantine is
        applied to a batch that was `CHECKED_OUT`, `open_checkout_count` is deliberately left
        unchanged."

        Design: Corner/state_machines/quarantine_voids_the_draft_tally_and_its_drawn_batch
        """
        scenario = fixtures.setup_draft_tally()
        physical_id = scenario["target_batch"]["id"]
        reason = "Torn seal reported by observer; retained as evidence"

        quarantined = validate_success(
            api_client.quarantine_ballot_batch(
                physical_id, {"reason": reason}, CUSTODY_OFFICER
            )
        )

        assertions.assert_ballot_batch(quarantined)
        assert quarantined["custody_status"] == "QUARANTINED"
        assert quarantined["quarantine_reason"] == reason
        tally = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert tally["status"] == "VOIDED"
        assert tally["net_error_votes"] is None
        drawn = fixtures.read_audit_batch(scenario["target_audit_batch"]["id"])
        assert drawn["tally_status"] == "VOIDED"
        assert drawn["retrieval_status"] == "RETRIEVED"
        assert quarantined["open_checkout_count"] == 1
        assert quarantined["checkout_cycle_count"] == 0
        events = fixtures.list_custody_events(physical_id)
        assert len(events) == 4
        assert events[3]["event_type"] == "QUARANTINE"
        assert events[3]["sequence_no"] == 4
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["status"] == "TALLYING"
        assert audit_round["counted_ballots"] == 0
        assert audit_round["discrepancy_count"] == 0
        assert fixtures.read_audit(scenario["audit"]["id"])["status"] == "TALLYING"
        assert (
            fixtures.read_election(scenario["election"]["id"])[
                "certification_risk_flag"
            ]
            is False
        )


class TestQuarantineSparesTheCountedDrawing:
    """Both branches of the cascade fire on one physical batch drawn twice."""

    def test_only_the_uncounted_drawing_of_the_shared_batch_is_voided(self):
        """PRD §3.2: "every drawn batch referencing this physical batch whose `tally_status`
        is `NOT_STARTED` or `IN_PROGRESS` has its `tally_status` set to `VOIDED`." §3.5: "The
        round's ledger is maintained over its tallies in `SUBMITTED` or `CERTIFIED`:
        `cumulative_net_error_votes` is the sum of their `net_error_votes` and
        `counted_ballots` is the sum of their drawn batches' ballot counts."

        Design: Corner/state_machines/quarantine_voids_only_the_uncounted_drawing_of_the_same_batch
        """
        scenario = fixtures.setup_two_audits_sharing_first_batch()
        counted = fixtures.open_manual_tally(
            scenario["rla_target"]["id"],
            scenario["team"]["id"],
            counted_votes=dict(constants.TEST_DEFAULTS["C1_BATCH_MACHINE_VOTES"]),
        )
        submitted = fixtures.submit_manual_tally(counted["id"], scenario["team"]["id"])
        assert submitted["status"] == "SUBMITTED"
        comparison_batches = fixtures.list_audit_batches(
            scenario["comparison"]["round"]["id"]
        )
        shared_drawing = comparison_batches[0]
        other_drawing = comparison_batches[1]
        assert shared_drawing["ballot_batch_id"] == scenario["shared_batch"]["id"]
        assert other_drawing["ballot_batch_id"] != scenario["shared_batch"]["id"]

        quarantined = validate_success(
            api_client.quarantine_ballot_batch(
                scenario["shared_batch"]["id"],
                {"reason": "Ballot container damaged in transit"},
                CUSTODY_OFFICER,
            )
        )

        assert quarantined["custody_status"] == "QUARANTINED"
        tally = fixtures.read_manual_tally(counted["id"])
        assert tally["status"] == "SUBMITTED"
        assert tally["net_error_votes"] == 0
        rla_drawing = fixtures.read_audit_batch(scenario["rla_target"]["id"])
        assert rla_drawing["tally_status"] == "COUNTED"
        assert rla_drawing["retrieval_status"] == "RETRIEVED"
        voided = fixtures.read_audit_batch(shared_drawing["id"])
        assert voided["tally_status"] == "VOIDED"
        assert voided["retrieval_status"] == "PENDING_RETRIEVAL"
        assert fixtures.read_audit_batch(other_drawing["id"])["tally_status"] == (
            "NOT_STARTED"
        )
        rla_round = fixtures.read_audit_round(scenario["rla"]["round"]["id"])
        assert rla_round["counted_ballots"] == 1000
        assert rla_round["discrepancy_count"] == 0
        assert rla_round["cumulative_net_error_votes"] == 0
        assert fixtures.read_audit(scenario["rla"]["audit"]["id"])["status"] == "TALLYING"
        assert fixtures.read_audit(scenario["comparison"]["audit"]["id"])["status"] == (
            "SAMPLING"
        )
        _findings, meta = validate_paginated(
            api_client.list_discrepancies(AUDIT_MANAGER, params={"limit": 100})
        )
        assert meta["total_count"] == 0


class TestDeadlockedInterpretation:
    """An even split at quorum lands in DEADLOCKED and moves no ballot."""

    def test_an_abstention_meets_quorum_on_a_tie_and_leaves_the_ballot_ambiguous(self):
        """PRD §3.7: "Once quorum is met, an equal `accept_count` and `reject_count` makes the
        referral `DEADLOCKED` with `final_determination` left null". §3.7: "When no referral of
        the tally remains `PENDING` — whether the last one was adjudicated or deadlocked — the
        tally moves from `PENDING_ADJUDICATION` back to `SUBMITTED`".

        Design: Corner/state_machines/interpretation_deadlocks_on_even_split_and_returns_the_tally_to_submitted
        """
        scenario = fixtures.setup_pending_adjudication(
            counted_votes={"ALVAREZ": 521, "BRENNAN": 478}
        )
        interpretation_id = scenario["interpretation"]["id"]
        assert scenario["interpretation"]["status"] == "PENDING"
        assert scenario["submitted_tally"]["net_error_votes"] == 7

        first = fixtures.cast_board_vote(interpretation_id, BOARD_ONE, "DEM", "ACCEPT")
        fixtures.cast_board_vote(interpretation_id, BOARD_TWO, "REP", "REJECT")
        third = fixtures.cast_board_vote(
            interpretation_id, BOARD_THREE, "DEM", "ABSTAIN"
        )

        assert first["votes_cast"] == 1
        assert first["quorum_met"] is False
        assert first["status"] == "PENDING"
        assertions.assert_ballot_interpretation(third)
        assert third["status"] == "DEADLOCKED"
        assert third["final_determination"] is None
        assert third["votes_cast"] == 3
        assert third["quorum_met"] is True
        assert third["accept_count"] == 1
        assert third["reject_count"] == 1
        assert len(third["board_votes"]) == 3
        tally = fixtures.read_manual_tally(scenario["manual_tally"]["id"])
        assert tally["status"] == "SUBMITTED"
        assert tally["ambiguous_ballot_count"] == 1
        assert tally["no_vote_count"] == 0
        assert tally["counted_votes"] == {"ALVAREZ": 521, "BRENNAN": 478}
        assert tally["net_error_votes"] == 7
        audit_round = fixtures.read_audit_round(scenario["round"]["id"])
        assert audit_round["cumulative_net_error_votes"] == 7
        assert audit_round["discrepancy_count"] == 1
