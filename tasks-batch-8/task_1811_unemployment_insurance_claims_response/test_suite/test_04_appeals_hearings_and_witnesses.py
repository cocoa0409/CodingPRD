"""Appeal lifecycle (remand cycles, withdrawal cascades), hearing scheduling
conflicts (referee buffer, witness containment), continuances, and the
readiness gate on holding a hearing."""
from test_helpers import (
    ApiErrorId,
    TEST_USERS,
    add_witness,
    appeal_determination,
    create_state_rule,
    determine_claim,
    get_appeal,
    get_claim,
    get_determination,
    get_hearing,
    get_witness,
    prep_witness_once,
    prep_witness_to_ready,
    schedule_hearing,
    set_clock,
    setup_appealed_claim,
    setup_docketed_hearing,
    setup_heard_appeal,
    validate_error,
    validate_success,
)

ANALYST = TEST_USERS["claims_analyst_headers"]
LIAISON = TEST_USERS["agency_liaison_headers"]


class TestRemandReadjudicationCycle:
    def test_remand_reopens_adjudication(self, api):
        """PRD §3.5: "**Remand.** The appeal becomes `REMANDED`, the
        determination becomes `REVERSED`, and the claim reopens from
        `HEARING_PENDING` to `UNDER_ADJUDICATION`, where a fresh determination
        restarts the loop."

        Design: Difficulty/non_linear_state_machine/appeal_remand_readjudication_cycle
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_heard_appeal(referee_id="ref-remand-1")
        assert ctx["appeal"]["status"] == "HEARD"

        decided = validate_success(
            api.decide_appeal(ctx["appeal"]["id"], "REMAND", LIAISON), 200)
        assert decided["status"] == "REMANDED"
        assert get_claim(ctx["claim"]["id"])["status"] == "UNDER_ADJUDICATION"
        assert get_determination(ctx["determination"]["id"])["status"] == "REVERSED"

    def test_reappeal_after_remand_increments_round_number(self, api):
        """PRD §3.5: "A re-appeal filed in the new cycle carries a
        `round_number` one greater than the remanded appeal's."

        Design: Difficulty/non_linear_state_machine/appeal_remand_readjudication_cycle
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_heard_appeal(referee_id="ref-remand-2")
        validate_success(api.decide_appeal(ctx["appeal"]["id"], "REMAND", LIAISON), 200)
        assert ctx["appeal"]["round_number"] == 1

        # The reopened claim is adjudicated again and re-appealed.
        det2 = determine_claim(ctx["claim"]["id"], outcome="DENIED",
                               mailed_at="2026-08-06T09:00:00Z")
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"
        appeal2 = appeal_determination(det2["id"], appellant="CLAIMANT",
                                       grounds="Claimant seeks review after remand.",
                                       as_liaison=True)
        assert appeal2["status"] == "FILED"
        assert appeal2["round_number"] == 2


class TestContinuanceReentryCycle:
    def test_continuance_increments_count_and_replaces_interval(self, api):
        """PRD §3.5: "A granted continuance increments `continuance_count` by
        one, replaces `scheduled_start` and `scheduled_end`, and passes the
        hearing through `CONTINUED` straight back into `SCHEDULED` — an
        immediate re-entry, not a resting state."

        Design: Difficulty/non_linear_state_machine/hearing_continuance_reentry_cycle
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-cont-1")

        continued = validate_success(
            api.continue_hearing(ctx["hearing"]["id"], "2026-08-21T14:00:00Z",
                                 "2026-08-21T15:00:00Z", ANALYST), 200)
        assert continued["status"] == "SCHEDULED"
        assert continued["continuance_count"] == 1
        assert continued["scheduled_start"] == "2026-08-21T14:00:00Z"
        assert continued["scheduled_end"] == "2026-08-21T15:00:00Z"

    def test_continuance_reruns_referee_overlap_check(self, api):
        """PRD §3.5: "the proposed new interval must pass both the referee
        buffer-overlap check and the witness availability containment check
        again."
        PRD §3.5: "the same referee may hold no other `SCHEDULED` or `HELD`
        hearing whose interval, expanded by thirty minutes on both sides,
        intersects the new one — a conflict is rejected with
        `ERR_REFEREE_DOUBLE_BOOKED`."

        Design: Difficulty/non_linear_state_machine/hearing_continuance_reentry_cycle
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        first = setup_docketed_hearing(referee_id="ref-cont-x")
        second = setup_docketed_hearing(
            referee_id="ref-cont-x", start="2026-08-21T14:00:00Z",
            end="2026-08-21T15:00:00Z")

        # Move the first hearing into the second's buffered window.
        err = api.continue_hearing(first["hearing"]["id"], "2026-08-21T14:30:00Z",
                                   "2026-08-21T15:30:00Z", ANALYST)
        validate_error(err, ApiErrorId.ERR_REFEREE_DOUBLE_BOOKED, 409)
        after = get_hearing(first["hearing"]["id"])
        assert after["continuance_count"] == 0
        assert after["scheduled_start"] == "2026-08-20T14:00:00Z"
        assert get_hearing(second["hearing"]["id"])["status"] == "SCHEDULED"

    def test_continuance_limit_fourth_rejected(self, api):
        """PRD §3.5: "A `ClaimsAnalyst` may reschedule a hearing only while its
        `continuance_count` is below three (a third request beyond that is
        rejected with `ERR_CONTINUANCE_LIMIT`)"

        Design: Corner/state_machines/continuance_limit_fourth_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-cont-lim")
        hearing_id = ctx["hearing"]["id"]
        for start in ("2026-08-21T14:00:00Z", "2026-08-24T14:00:00Z",
                      "2026-08-25T14:00:00Z"):
            ok = validate_success(
                api.continue_hearing(hearing_id, start,
                                     start.replace("14:00", "15:00"), ANALYST), 200)
            assert ok["status"] == "SCHEDULED"
        assert get_hearing(hearing_id)["continuance_count"] == 3

        err = api.continue_hearing(hearing_id, "2026-08-26T14:00:00Z",
                                   "2026-08-26T15:00:00Z", ANALYST)
        validate_error(err, ApiErrorId.ERR_CONTINUANCE_LIMIT, 409)
        after = get_hearing(hearing_id)
        assert after["continuance_count"] == 3
        assert after["scheduled_start"] == "2026-08-25T14:00:00Z"


class TestAppealWithdrawalCascade:
    def test_withdrawal_closes_hearing_and_freezes_witness_prep(self, api):
        """PRD §3.5: "A `ClaimsAnalyst` may withdraw an appeal while it is
        `FILED` or `DOCKETED` (otherwise `ERR_APPEAL_NOT_WITHDRAWABLE`): the
        appeal becomes `WITHDRAWN`, the determination becomes `FINAL`, the
        claim returns from `HEARING_PENDING` to `DETERMINED`, and any hearing
        for that appeal still in `SCHEDULED` or `PREP_IN_PROGRESS` is closed;
        witness rows remain for audit with their `prep_status` frozen."

        Design: Difficulty/transitive_cascade/appeal_withdrawal_hearing_witness_freeze_chain
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-wd-1")
        witness = add_witness(ctx["hearing"]["id"], full_name="HR Hanna",
                              witness_role="HR_CUSTODIAN")
        prep_witness_once(ctx["hearing"]["id"], witness["id"])
        assert get_witness(ctx["hearing"]["id"], witness["id"])["prep_status"] == "BRIEFED"

        withdrawn = validate_success(
            api.withdraw_appeal(ctx["appeal"]["id"], ANALYST), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_determination(ctx["determination"]["id"])["status"] == "FINAL"
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"
        assert get_hearing(ctx["hearing"]["id"])["status"] == "CLOSED"
        # The witness froze mid-pipeline at BRIEFED.
        assert get_witness(ctx["hearing"]["id"],
                           witness["id"])["prep_status"] == "BRIEFED"

    def test_withdrawal_from_filed_then_close_succeeds(self, api):
        """PRD §3.5: "A `ClaimsAnalyst` may withdraw an appeal while it is
        `FILED` or `DOCKETED` (otherwise `ERR_APPEAL_NOT_WITHDRAWABLE`): the
        appeal becomes `WITHDRAWN`, the determination becomes `FINAL`, the
        claim returns from `HEARING_PENDING` to `DETERMINED`"

        Design: Difficulty/transitive_cascade/appeal_withdrawal_hearing_witness_freeze_chain
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_appealed_claim()
        assert ctx["appeal"]["status"] == "FILED"

        withdrawn = validate_success(
            api.withdraw_appeal(ctx["appeal"]["id"], ANALYST), 200)
        assert withdrawn["status"] == "WITHDRAWN"
        assert get_determination(ctx["determination"]["id"])["status"] == "FINAL"
        assert get_claim(ctx["claim"]["id"])["status"] == "DETERMINED"

        closed = validate_success(api.close_claim(ctx["claim"]["id"], ANALYST), 200)
        assert closed["status"] == "CLOSED"


class TestHearingHoldReadinessGate:
    def test_hold_blocked_until_every_witness_ready(self, api):
        """PRD §3.5: "An `AgencyLiaison` marks the hearing held only when it is
        `READY` — which, by the rule above, means every witness is `READY` —
        otherwise `ERR_HEARING_NOT_READY`."

        Design: Difficulty/cross_entity_state_dependency/hearing_hold_requires_all_witnesses_ready
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-hold-1")
        witness = add_witness(ctx["hearing"]["id"])
        prep_witness_once(ctx["hearing"]["id"], witness["id"])  # BRIEFED only

        err = api.hold_hearing(ctx["hearing"]["id"], LIAISON)
        validate_error(err, ApiErrorId.ERR_HEARING_NOT_READY, 409)
        assert get_hearing(ctx["hearing"]["id"])["status"] == "PREP_IN_PROGRESS"
        assert get_appeal(ctx["appeal"]["id"])["status"] == "DOCKETED"

    def test_ready_hearing_held_moves_appeal_to_heard(self, api):
        """PRD §3.5: "When every witness has reached `READY` and at least one
        witness exists, the hearing automatically becomes `READY`."
        PRD §3.5: "The hearing moves from `READY` to `HELD`, and the appeal
        moves from `DOCKETED` to `HEARD`."

        Design: Difficulty/cross_entity_state_dependency/hearing_hold_requires_all_witnesses_ready
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-hold-2")
        witness = add_witness(ctx["hearing"]["id"])
        prep_witness_to_ready(ctx["hearing"]["id"], witness["id"])
        assert get_witness(ctx["hearing"]["id"],
                           witness["id"])["prep_status"] == "READY"
        assert get_hearing(ctx["hearing"]["id"])["status"] == "READY"

        held = validate_success(api.hold_hearing(ctx["hearing"]["id"], LIAISON), 200)
        assert held["status"] == "HELD"
        assert get_appeal(ctx["appeal"]["id"])["status"] == "HEARD"

    def test_decide_before_hearing_rejected(self, api):
        """PRD §3.5: "The appeal decision, recorded by an `AgencyLiaison` with
        a `decision`, requires the appeal to be `HEARD` (otherwise
        `ERR_APPEAL_NOT_HEARD`)"

        Design: Corner/state_machines/appeal_decide_before_hearing_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_appealed_claim()

        err = api.decide_appeal(ctx["appeal"]["id"], "AFFIRM", LIAISON)
        validate_error(err, ApiErrorId.ERR_APPEAL_NOT_HEARD, 409)
        assert get_appeal(ctx["appeal"]["id"])["status"] == "FILED"


class TestRefereeBufferOverlap:
    def test_referee_buffer_overlap_rejected(self, api):
        """PRD §3.5: "the same referee may hold no other `SCHEDULED` or `HELD`
        hearing whose interval, expanded by thirty minutes on both sides,
        intersects the new one — a conflict is rejected with
        `ERR_REFEREE_DOUBLE_BOOKED`."

        Design: Difficulty/resource_temporal_overlap/referee_buffer_overlap_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        setup_docketed_hearing(referee_id="ref-buf-x")
        second = setup_appealed_claim()

        # Existing [14:00, 15:00] buffered to [13:30, 15:30]; 15:20 intersects.
        err = api.schedule_hearing(
            second["appeal"]["id"],
            {"claim_id": second["claim"]["id"],
             "scheduled_start": "2026-08-20T15:20:00Z",
             "scheduled_end": "2026-08-20T16:00:00Z",
             "referee_id": "ref-buf-x", "location": "Room B"},
            ANALYST)
        validate_error(err, ApiErrorId.ERR_REFEREE_DOUBLE_BOOKED, 409)
        assert get_appeal(second["appeal"]["id"])["status"] == "FILED"

    def test_referee_clear_of_buffer_is_scheduled(self, api):
        """PRD §3.5: "the same referee may hold no other `SCHEDULED` or `HELD`
        hearing whose interval, expanded by thirty minutes on both sides,
        intersects the new one — a conflict is rejected with
        `ERR_REFEREE_DOUBLE_BOOKED`. This buffer check runs at scheduling,
        again at every witness addition, and again at every continuance."

        Design: Difficulty/resource_temporal_overlap/referee_buffer_overlap_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        setup_docketed_hearing(referee_id="ref-buf-y")
        second = setup_appealed_claim()

        # 16:00 lies beyond the existing hearing's 15:30 buffered end.
        hearing = schedule_hearing(second["appeal"]["id"], second["claim"]["id"],
                                   scheduled_start="2026-08-20T16:00:00Z",
                                   scheduled_end="2026-08-20T17:00:00Z",
                                   referee_id="ref-buf-y", location="Room B")
        assert hearing["status"] == "SCHEDULED"
        assert get_appeal(second["appeal"]["id"])["status"] == "DOCKETED"


class TestWitnessAvailabilityContainment:
    def test_witness_availability_containment_rejected(self, api):
        """PRD §3.5: "The availability window must contain the entire hearing
        interval — `availability_start` at or before `scheduled_start` and
        `availability_end` at or after `scheduled_end` — or the addition is
        rejected with `ERR_WITNESS_UNAVAILABLE`."

        Design: Difficulty/resource_temporal_overlap/witness_availability_containment_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-wit-1")

        # Available 13:00-14:30, but the hearing runs 14:00-15:00.
        err = api.add_witness(
            ctx["hearing"]["id"],
            {"full_name": "Busy Bea", "witness_role": "HR_CUSTODIAN",
             "availability_start": "2026-08-20T13:00:00Z",
             "availability_end": "2026-08-20T14:30:00Z"},
            ANALYST)
        validate_error(err, ApiErrorId.ERR_WITNESS_UNAVAILABLE, 409)
        assert get_hearing(ctx["hearing"]["id"])["status"] == "SCHEDULED"

    def test_witness_exact_containment_accepted(self, api):
        """PRD §3.5: "The availability window must contain the entire hearing
        interval — `availability_start` at or before `scheduled_start` and
        `availability_end` at or after `scheduled_end`"
        PRD §3.5: "Adding the first witness moves the hearing from `SCHEDULED`
        to `PREP_IN_PROGRESS`."

        Design: Difficulty/resource_temporal_overlap/witness_availability_containment_rejected
        """
        set_clock("2026-08-03T09:00:00Z")
        create_state_rule("XX")
        ctx = setup_docketed_hearing(referee_id="ref-wit-2")

        # Availability exactly equals the hearing interval: "at or before" /
        # "at or after" is inclusive.
        witness = validate_success(
            api.add_witness(
                ctx["hearing"]["id"],
                {"full_name": "Exact Ed", "witness_role": "DIRECT_SUPERVISOR",
                 "availability_start": "2026-08-20T14:00:00Z",
                 "availability_end": "2026-08-20T15:00:00Z"},
                ANALYST), 201)
        assert witness["prep_status"] == "UNPREPARED"
        assert get_hearing(ctx["hearing"]["id"])["status"] == "PREP_IN_PROGRESS"
