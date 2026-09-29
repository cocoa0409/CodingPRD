"""Non-linear review loops and the transitive cascades they drive.

Three cyclic or parallel-dimension state machines are exercised here — the
prospectus revision loop, the monitoring report's two independent status
dimensions and the remedial-action reinspection loop — together with the two
long cascades that run out of a monitoring review: the failure direction
(report FAIL -> remedial action -> posture -> sale cancellation -> milestone
deferral) and the recovery direction (clearance -> milestone restoration ->
availability).
"""

from test_helpers import (
    ApiErrorId,
    api_client,
    approve_release_payload,
    assert_credit_conservation,
    assert_credits,
    assert_ledger_sequence,
    assert_ledger_shape,
    assert_score,
    bank_state,
    bank_version,
    cast_votes,
    create_vote_payload,
    finalize_prospectus,
    get_success_data,
    inspect_remedial_action,
    ledger_rows,
    milestone_state,
    open_monitoring_report,
    quote_credits,
    remedial_action_state,
    remedial_actions_for_report,
    reserve_sale,
    review_monitoring_report,
    sale_state,
    set_clock,
    setup_bank_under_review,
    setup_monitoring_ready_bank,
    setup_sellable_bank_with_second_milestone,
    submit_monitoring_report,
    submit_remedial_work,
    validate_error,
)

# A year-1 measurement set that misses both effective standards: hydroperiod
# 60 against a GTE 120 threshold and invasive cover 40.0 against LTE 10.0.
YEAR1_FAILING_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 60},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 40.0},
]

# A year-3 measurement set that misses three of the four standards and meets
# the stem-density standard exactly at its threshold.
YEAR3_FAILING_MEASUREMENTS = [
    {"standard_code": "HYDROPERIOD_DAYS", "measured_value": 96},
    {"standard_code": "INVASIVE_COVER_PCT", "measured_value": 20.0},
    {"standard_code": "NATIVE_COVER_PCT", "measured_value": 60.0},
    {"standard_code": "STEM_DENSITY_PER_ACRE", "measured_value": 400},
]


def _world_with_open_remedial_action():
    """A sellable bank whose CONSTRUCTION_COMPLETE milestone is CLAIMED and
    whose accepted year-1 monitoring report failed, so the failure cascade has
    already opened a round-1 remedial action and frozen the released credits.

    Returns the world, the accepted report and the remedial action.
    """
    world = setup_sellable_bank_with_second_milestone(clock="2027-09-15T00:00:00Z")
    report = open_monitoring_report(
        world,
        monitoring_year=1,
        window_start="2027-06-01T00:00:00Z",
        window_end="2027-09-01T00:00:00Z",
        measurements_array=YEAR1_FAILING_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    report = review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)
    actions = remedial_actions_for_report(world, report["id"])
    assert len(actions) == 1, f"expected one remedial action, got {len(actions)}"
    return world, report, actions[0]


def _world_with_reserved_sale_and_failing_year3_report():
    """A sellable bank at clock 2029-09-05 with the CONSTRUCTION_COMPLETE
    milestone CLAIMED, a RESERVED 4.00-credit sale holding credits, and a
    SUBMITTED year-3 monitoring report whose measurements will score FAIL.

    Returns the world, the reserved sale and the submitted report.
    """
    world = setup_sellable_bank_with_second_milestone(clock="2029-09-05T00:00:00Z")
    sale = quote_credits(world, 4.00)
    sale = reserve_sale(world, sale["id"])
    report = open_monitoring_report(
        world,
        monitoring_year=3,
        window_start="2029-06-01T00:00:00Z",
        window_end="2029-09-01T00:00:00Z",
        measurements_array=YEAR3_FAILING_MEASUREMENTS,
    )
    submit_monitoring_report(world, report["id"])
    return world, sale, report


def _prospectus_after_split_round_one():
    """A prospectus UNDER_REVIEW carrying one CONCUR, one OBJECT and one
    ABSTAIN in round 1, over a bank whose work plan is already SUBMITTED.

    The OBJECT is cast by the STATE_DEQ seat, which holds no veto authority,
    so the round fails only on the supermajority test.
    """
    world = setup_bank_under_review(work_plan_state="SUBMITTED")
    prospectus_id = world["prospectus"]["id"]
    epa_vote = get_success_data(
        api_client.create_prospectus_vote(
            prospectus_id, create_vote_payload("CONCUR"), world["member_headers"][1]
        )
    )
    deq_vote = get_success_data(
        api_client.create_prospectus_vote(
            prospectus_id,
            create_vote_payload(
                "OBJECT",
                comment="Hydroperiod target not defensible for a depressional system.",
            ),
            world["member_headers"][2],
        )
    )
    corps_vote = get_success_data(
        api_client.create_prospectus_vote(
            prospectus_id, create_vote_payload("ABSTAIN"), world["member_headers"][0]
        )
    )
    return world, {"epa": epa_vote, "deq": deq_vote, "corps": corps_vote}


def _read_prospectus(world):
    return get_success_data(
        api_client.get_prospectus(world["prospectus"]["id"], world["chair_headers"])
    )


class TestProspectusRevisionCycle:
    """The UNDER_REVIEW -> REVISION_REQUESTED -> SUBMITTED -> UNDER_REVIEW loop."""

    def test_round_one_short_of_supermajority_requests_revision_and_rescopes_tallies(self):
        """A round of 1 CONCUR / 1 OBJECT / 1 ABSTAIN misses the two-of-three
        supermajority, so the first finalisation requests a revision, raises
        revision_round to 2 and re-scopes every tally to the new round.

        PRD §3.3: "Then the supermajority: the concur tally must be at least two-thirds of the votes cast in the round, with that two-thirds threshold rounded **up** to a whole number of votes, so five votes cast require four concurrences and four votes cast require three."
        PRD §3.3: "When quorum is met, no veto stands, the supermajority is *not* reached and the prospectus is still in its first review round, it goes `UNDER_REVIEW → REVISION_REQUESTED` and its `revision_round` rises by one."
        PRD §3.3: "The revision-request branch additionally resets the round's tallies: the concur, object and abstain counts and the veto flag are all recomputed against the new revision round and are therefore all zero and false until fresh votes arrive."
        PRD §3.3: "Its `is_veto` flag is derived: true precisely when the position is `OBJECT` **and** the casting member holds veto authority."
        Design: Difficulty/non_linear_state_machine/prospectus_revision_cycle_resets_tallies_then_approves_in_round_two
        """
        world, votes = _prospectus_after_split_round_one()

        assert votes["deq"]["is_veto"] is False, (
            "an OBJECT from the STATE_DEQ seat carries no veto authority"
        )

        before = _read_prospectus(world)
        assert before["status"] == "UNDER_REVIEW", (
            f"the first vote of the round opens the review, got {before['status']}"
        )
        assert before["concur_count"] == 1, f"concur_count: {before['concur_count']}"
        assert before["object_count"] == 1, f"object_count: {before['object_count']}"
        assert before["abstain_count"] == 1, f"abstain_count: {before['abstain_count']}"
        assert before["revision_round"] == 1, "round 1 before any finalisation"
        assert before["veto_recorded"] is False, "no veto was cast in round 1"

        after = finalize_prospectus(world)
        assert after["status"] == "REVISION_REQUESTED", (
            f"a first-round supermajority miss requests a revision, got {after['status']}"
        )
        assert after["revision_round"] == 2, (
            f"revision_round rises by one, got {after['revision_round']}"
        )
        assert after["concur_count"] == 0, (
            f"round-1 concurrences stop counting, got {after['concur_count']}"
        )
        assert after["object_count"] == 0, (
            f"round-1 objections stop counting, got {after['object_count']}"
        )
        assert after["abstain_count"] == 0, (
            f"round-1 abstentions stop counting, got {after['abstain_count']}"
        )
        assert after["veto_recorded"] is False, "the veto flag is recomputed to false"
        assert after["decided_at"] is not None, "the revision branch stamps decided_at"
        assert after["decision_recorded_by"], "the revision branch records the chair"

    def test_round_two_unanimous_concurrence_approves_without_a_further_round_increment(self):
        """Re-entering the loop is not a no-op: resubmission clears
        review_opened_at, the first round-2 vote reopens the review, and three
        round-2 concurrences approve the prospectus while revision_round stays
        at 2.

        PRD §3.3: "A revised prospectus is resubmitted by its sponsor, advancing `REVISION_REQUESTED → SUBMITTED`, restamping `submitted_at`, clearing `review_opened_at` back to null because a fresh round has no opened review yet, and again showing all tallies at zero for the new round; resubmission is admissible only while the revision round has not passed the second-round ceiling."
        PRD §3.3: "The first vote of a round auto-advances the prospectus `SUBMITTED → UNDER_REVIEW` and stamps `review_opened_at` with the clock."
        PRD §3.3: "When quorum is met, no veto stands, the supermajority is reached, and the bank additionally has a work plan in either `SUBMITTED` or `APPROVED` status, the prospectus goes `UNDER_REVIEW → APPROVED`; if no such work plan exists the finalisation is rejected with `ERR_WORK_PLAN_MISSING`."
        Design: Difficulty/non_linear_state_machine/prospectus_revision_cycle_resets_tallies_then_approves_in_round_two
        """
        world, _votes = _prospectus_after_split_round_one()
        finalize_prospectus(world)
        prospectus_id = world["prospectus"]["id"]

        resubmitted = get_success_data(
            api_client.submit_prospectus(prospectus_id, world["sponsor_headers"])
        )
        assert resubmitted["status"] == "SUBMITTED", (
            f"REVISION_REQUESTED resubmits to SUBMITTED, got {resubmitted['status']}"
        )
        assert resubmitted["review_opened_at"] is None, (
            "a fresh round has no opened review yet, so review_opened_at is null"
        )
        assert resubmitted["concur_count"] == 0, "all tallies read zero for the new round"
        assert resubmitted["revision_round"] == 2, "still the second round"

        get_success_data(
            api_client.create_prospectus_vote(
                prospectus_id, create_vote_payload("CONCUR"), world["member_headers"][1]
            )
        )
        reopened = _read_prospectus(world)
        assert reopened["status"] == "UNDER_REVIEW", (
            f"the first round-2 vote reopens the review, got {reopened['status']}"
        )
        assert reopened["review_opened_at"] is not None, (
            "the first vote of the round stamps review_opened_at"
        )

        for member_index in (2, 0):
            get_success_data(
                api_client.create_prospectus_vote(
                    prospectus_id,
                    create_vote_payload("CONCUR"),
                    world["member_headers"][member_index],
                )
            )

        decided = finalize_prospectus(world)
        assert decided["status"] == "APPROVED", (
            f"three round-2 concurrences clear the supermajority, got {decided['status']}"
        )
        assert decided["concur_count"] == 3, (
            f"the round-2 concur tally is 3, got {decided['concur_count']}"
        )
        assert decided["revision_round"] == 2, (
            f"approval does not increment the round, got {decided['revision_round']}"
        )
        assert decided["veto_recorded"] is False, "no veto stood in round 2"

        bank = bank_state(world)
        assert bank["status"] == "PROSPECTUS_REVIEW", (
            "approving a prospectus does not by itself execute the instrument, "
            f"got {bank['status']}"
        )

    def test_prospectus_votes_stay_permanently_scoped_to_the_round_they_were_cast_in(self):
        """Six vote rows survive the loop, three stamped with revision_round 1
        and three with revision_round 2, and only the round-2 rows feed the
        tallies that decided the second finalisation.

        PRD §3.3: "The vote row records the `prospectus_id` it was cast against, the `irt_member_id` of the caster, and a copy of the prospectus's `revision_round` at cast time, so votes are permanently scoped to a single round."
        PRD §3.3: "Each vote raises exactly one of `concur_count`, `object_count` or `abstain_count` by one — the tallies count only votes bearing the prospectus's current revision round — and a veto vote raises the object tally and additionally sets `veto_recorded` to true."
        Design: Difficulty/non_linear_state_machine/prospectus_revision_cycle_resets_tallies_then_approves_in_round_two
        """
        world, votes = _prospectus_after_split_round_one()
        for vote in votes.values():
            assert vote["revision_round"] == 1, (
                f"a round-1 vote is stamped with round 1, got {vote['revision_round']}"
            )
        finalize_prospectus(world)
        prospectus_id = world["prospectus"]["id"]
        get_success_data(
            api_client.submit_prospectus(prospectus_id, world["sponsor_headers"])
        )
        round_two = cast_votes(world, ["CONCUR", "CONCUR", "CONCUR"])
        for vote in round_two:
            assert vote["revision_round"] == 2, (
                f"a round-2 vote is stamped with round 2, got {vote['revision_round']}"
            )

        all_votes = get_success_data(
            api_client.list_prospectus_votes(
                prospectus_id, world["chair_headers"], params={"limit": 100}
            )
        )
        assert len(all_votes) == 6, (
            f"all six votes across both rounds persist, got {len(all_votes)}"
        )
        rounds = sorted(v["revision_round"] for v in all_votes)
        assert rounds == [1, 1, 1, 2, 2, 2], (
            f"three votes per round survive the loop, got {rounds}"
        )

        decided = finalize_prospectus(world)
        assert decided["status"] == "APPROVED", (
            f"the round-2 tally alone decides the outcome, got {decided['status']}"
        )
        assert decided["object_count"] == 0, (
            "the round-1 objection no longer counts, got "
            f"{decided['object_count']}"
        )
        assert decided["abstain_count"] == 0, (
            "the round-1 abstention no longer counts, got "
            f"{decided['abstain_count']}"
        )


def _submitted_year1_report():
    """A bank in INSTRUMENT_EXECUTED with its four performance standards
    materialised and a SUBMITTED year-1 monitoring report over the half-open
    window [2027-03-01, 2027-06-01) carrying passing measurements.

    Returns the world and the submitted report.
    """
    world = setup_monitoring_ready_bank()
    set_clock("2027-06-15T00:00:00Z")
    report = open_monitoring_report(world, monitoring_year=1)
    assert report["compliance_status"] == "UNEVALUATED", (
        "a new report opens with its compliance status UNEVALUATED"
    )
    report = submit_monitoring_report(world, report["id"])
    return world, report


class TestMonitoringReportParallelDimensions:
    """One report row carries a paperwork dimension and an ecological one."""

    def test_returning_a_report_advances_only_the_paperwork_dimension(self):
        """The RETURN branch moves review_status to RETURNED and raises
        return_count, but writes nothing on the ecological dimension, creates
        no remedial action and does not touch the bank at all.

        PRD §3.7: "Returning advances the review status `SUBMITTED → RETURNED`, raises `return_count` by one, records the acting member into `reviewed_by_member_id`, stamps `reviewed_at`, and requires a `return_reason`."
        PRD §3.7: "The return branch performs no scoring at all: the compliance status stays `UNEVALUATED`, no remedial action is created, no milestone is deferred, no posture changes, and the bank's `version` is *not* incremented."
        Design: Difficulty/non_linear_state_machine/monitoring_report_return_leaves_compliance_dimension_unevaluated
        """
        world, report = _submitted_year1_report()
        before = bank_state(world)

        returned = review_monitoring_report(
            world,
            report["id"],
            "RETURN",
            member_index=2,
            return_reason="Piezometer calibration records missing for two transects.",
        )

        assert returned["review_status"] == "RETURNED", (
            f"the paperwork dimension advances, got {returned['review_status']}"
        )
        assert returned["compliance_status"] == "UNEVALUATED", (
            "the ecological dimension is untouched by a return, got "
            f"{returned['compliance_status']}"
        )
        assert returned["attainment_score"] is None, (
            f"the return branch scores nothing, got {returned['attainment_score']}"
        )
        assert returned["failed_standard_codes"] == [], (
            f"no standard is judged on a return, got {returned['failed_standard_codes']}"
        )
        assert returned["return_count"] == 1, (
            f"return_count rises by one, got {returned['return_count']}"
        )
        assert returned["reviewed_by_member_id"] == world["members"][2]["id"], (
            "the returning member is recorded as the reviewer"
        )
        assert returned["reviewed_at"] is not None, "the return branch stamps reviewed_at"

        after = bank_state(world)
        assert after["version"] == before["version"], (
            "the return branch does not increment the bank version: "
            f"{before['version']} -> {after['version']}"
        )
        assert after["status"] == "INSTRUMENT_EXECUTED", (
            f"a returned report never moves the bank, got {after['status']}"
        )
        assert after["sales_posture"] == before["sales_posture"], (
            "no posture change follows a return: "
            f"{before['sales_posture']} -> {after['sales_posture']}"
        )
        assert remedial_actions_for_report(world, report["id"]) == [], (
            "the return branch creates no remedial action"
        )

    def test_accepting_the_resubmitted_report_advances_both_dimensions_at_once(self):
        """Resubmission returns the paperwork dimension to SUBMITTED without
        disturbing return_count, and the ACCEPT branch then scores the report
        against the year-1 weight sum of 0.550 and carries the bank into
        MONITORING.

        PRD §3.7: "Submission by the owning sponsor advances the review status `DRAFT → SUBMITTED` and stamps `submitted_at` with the logical clock; a returned report is resubmitted the same way, advancing `RETURNED → SUBMITTED` and restamping `submitted_at`."
        PRD §3.7: "The report's `attainment_score` is the sum of those already-rounded contributions divided by the sum of the effective standards' weights as supplied — the denominator uses the unrounded weights and covers only the standards effective in this year, so a report in an early monitoring year is scored against a denominator smaller than 1.000 — with the quotient rounded half up to 4 decimal places."
        PRD §3.7: "If the bank has never had an accepted report before, this acceptance additionally carries the bank `INSTRUMENT_EXECUTED → MONITORING`."
        Design: Difficulty/non_linear_state_machine/monitoring_report_return_leaves_compliance_dimension_unevaluated
        """
        world, report = _submitted_year1_report()
        review_monitoring_report(
            world,
            report["id"],
            "RETURN",
            member_index=2,
            return_reason="Piezometer calibration records missing for two transects.",
        )

        resubmitted = submit_monitoring_report(world, report["id"])
        assert resubmitted["review_status"] == "SUBMITTED", (
            f"RETURNED resubmits to SUBMITTED, got {resubmitted['review_status']}"
        )
        assert resubmitted["return_count"] == 1, (
            f"resubmission does not reset return_count, got {resubmitted['return_count']}"
        )
        assert resubmitted["compliance_status"] == "UNEVALUATED", (
            "the ecological dimension is still unevaluated, got "
            f"{resubmitted['compliance_status']}"
        )

        accepted = review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)
        assert accepted["review_status"] == "ACCEPTED", (
            f"the paperwork dimension reaches ACCEPTED, got {accepted['review_status']}"
        )
        assert_score(accepted["attainment_score"], 1.0000)
        assert accepted["compliance_status"] == "PASS", (
            f"no standard failed, so compliance is PASS, got {accepted['compliance_status']}"
        )
        assert accepted["failed_standard_codes"] == [], (
            f"no failed codes on a passing year, got {accepted['failed_standard_codes']}"
        )
        assert accepted["reviewed_by_member_id"] == world["members"][1]["id"], (
            "the accepting member overwrites the earlier returning reviewer"
        )
        assert accepted["return_count"] == 1, (
            f"acceptance leaves return_count alone, got {accepted['return_count']}"
        )

        bank = bank_state(world)
        assert bank["status"] == "MONITORING", (
            "the bank's first accepted report carries it out of INSTRUMENT_EXECUTED, "
            f"got {bank['status']}"
        )
        assert remedial_actions_for_report(world, report["id"]) == [], (
            "a passing acceptance opens no remedial action"
        )


class TestRemedialReinspectionCycle:
    """WORK_SUBMITTED -> REINSPECTION -> OPEN loops until the third round."""

    def test_not_cleared_reinspections_reopen_the_action_with_a_higher_round(self):
        """The same NOT_CLEARED payload loops the action back to OPEN twice,
        raising round_number to 2 and then to 3 and clearing work_submitted_at
        each time, while nothing else in the world moves.

        PRD §3.7: "Submitting the work advances the action `OPEN → WORK_SUBMITTED` and stamps `work_submitted_at` with the clock, and it is admissible only while the logical clock has not passed the action's due date — on the due instant itself submission is still accepted, but past it the request is rejected with `ERR_REMEDIAL_PAST_DUE`."
        PRD §3.7: "An outcome of `NOT_CLEARED` sends the action round again, so long as rounds remain: with a round number below the ceiling of 3, the action goes `REINSPECTION → OPEN`, its `round_number` rises by one, its `work_submitted_at` is cleared back to null and a fresh due date is set."
        Design: Difficulty/non_linear_state_machine/remedial_action_reinspection_cycle_terminates_at_third_round
        """
        world, _report, action = _world_with_open_remedial_action()
        assert action["round_number"] == 1, (
            f"the cascade opens the action in round 1, got {action['round_number']}"
        )

        submitted = submit_remedial_work(world, action["id"])
        assert submitted["status"] == "WORK_SUBMITTED", (
            f"corrective work moves the action to WORK_SUBMITTED, got {submitted['status']}"
        )
        assert submitted["work_submitted_at"] is not None, (
            "submitting the work stamps work_submitted_at"
        )

        first = inspect_remedial_action(world, action["id"], "NOT_CLEARED", member_index=2)
        assert first["status"] == "OPEN", (
            f"a NOT_CLEARED below the ceiling reopens the action, got {first['status']}"
        )
        assert first["round_number"] == 2, (
            f"round_number rises to 2, got {first['round_number']}"
        )
        assert first["work_submitted_at"] is None, (
            "work_submitted_at is cleared back to null on the loop, got "
            f"{first['work_submitted_at']}"
        )
        assert first["due_at"] is not None, "a fresh due date is set on the new round"

        submit_remedial_work(world, action["id"])
        second = inspect_remedial_action(world, action["id"], "NOT_CLEARED", member_index=2)
        assert second["status"] == "OPEN", (
            f"the second NOT_CLEARED still reopens the action, got {second['status']}"
        )
        assert second["round_number"] == 3, (
            f"round_number rises to 3, got {second['round_number']}"
        )
        assert second["work_submitted_at"] is None, (
            "work_submitted_at is cleared again on the second loop"
        )

        bank = bank_state(world)
        assert bank["status"] == "MONITORING", (
            f"the loop leaves the bank in MONITORING, got {bank['status']}"
        )
        assert bank["sales_posture"] == "RESTRICTED", (
            "a non-terminal remedial action holds the posture at RESTRICTED, got "
            f"{bank['sales_posture']}"
        )
        sponsor = get_success_data(
            api_client.get_sponsor(world["sponsor"]["id"], world["sponsor_headers"])
        )
        assert sponsor["good_standing"] is True, (
            "the bank has not been suspended while rounds remain"
        )

    def test_third_not_cleared_inspection_fails_the_action_and_suspends_the_bank(self):
        """The identical NOT_CLEARED payload takes the terminal exit on the
        third pass: the action FAILS without a further round increment, the
        bank is suspended and frozen, the sponsor leaves good standing, and the
        FAILED action accepts no further work.

        PRD §3.7: "But an outcome of `NOT_CLEARED` on the third round exhausts the sponsor's patience allowance: the action goes `REINSPECTION → FAILED`, the bank goes `MONITORING → SUSPENDED` (or stays suspended if it already was), its posture is recomputed to `FROZEN`, every credit sale of the bank standing in `QUOTED` or `RESERVED` is cancelled with a reason of `BANK_POSTURE_RESTRICTED` with each formerly reserved sale appending a `HOLD_RELEASED` entry, the owning sponsor's `good_standing` is recomputed to false, and the bank's `version` increments by one."
        PRD §3.7: "The action passes through `REINSPECTION` within the same request and resolves immediately; the inspection is admissible only on an action standing in `WORK_SUBMITTED` when the request arrives, and anything else is `ERR_REMEDIAL_STATE_INVALID`."
        Design: Difficulty/non_linear_state_machine/remedial_action_reinspection_cycle_terminates_at_third_round
        """
        world, _report, action = _world_with_open_remedial_action()
        for _ in range(2):
            submit_remedial_work(world, action["id"])
            inspect_remedial_action(world, action["id"], "NOT_CLEARED", member_index=2)

        submit_remedial_work(world, action["id"])
        before_version = bank_state(world)["version"]
        third = inspect_remedial_action(world, action["id"], "NOT_CLEARED", member_index=2)

        assert third["status"] == "FAILED", (
            f"the third NOT_CLEARED exhausts the rounds, got {third['status']}"
        )
        assert third["round_number"] == 3, (
            f"the terminal exit does not increment the round, got {third['round_number']}"
        )

        bank = bank_state(world)
        assert bank["status"] == "SUSPENDED", (
            f"a failed remedial action suspends the bank, got {bank['status']}"
        )
        assert bank["sales_posture"] == "FROZEN", (
            f"a SUSPENDED bank's posture is FROZEN, got {bank['sales_posture']}"
        )
        assert bank["version"] == before_version + 1, (
            "the failure cascade increments the bank version once for the request: "
            f"{before_version} -> {bank['version']}"
        )

        sponsor = get_success_data(
            api_client.get_sponsor(world["sponsor"]["id"], world["sponsor_headers"])
        )
        assert sponsor["good_standing"] is False, (
            "a suspended bank takes its sponsor out of good standing"
        )

        rejected = api_client.submit_remedial_work(action["id"], world["sponsor_headers"])
        validate_error(rejected, ApiErrorId.ERR_REMEDIAL_STATE_INVALID, 409)

    def test_reinspection_cycle_leaves_the_deferred_milestone_and_its_hold_untouched(self):
        """Across every pass of the loop the deferred milestone stays DEFERRED,
        the 14.82-credit hold stays exactly where the failure cascade put it,
        and the ledger gains no further row.

        PRD §3.7: "The first hop creates a remedial action against this report. It opens in `OPEN` status with `round_number` at 1, its `monitoring_report_id` naming the failing report, its `opened_at` stamped with the logical clock, its `due_at` set to that clock plus 365 days, and its `corrective_scope` auto-generated as the literal text `REMEDIATE: ` followed by the failed standard codes joined by commas in the same ascending order they were listed in."
        PRD §3.7: "Nothing else moves — the deferred milestone stays `DEFERRED`, its hold stays exactly where it is, and no ledger entry is written."
        PRD §3.7: "The consequence of the pinned order is exact and worth stating: at the end of such a request the bank's credits on hold equal the remedial action's held credits and its available credits are exactly 0.00 — every unsold released credit of the bank is frozen."
        Design: Difficulty/non_linear_state_machine/remedial_action_reinspection_cycle_terminates_at_third_round
        """
        world, report, action = _world_with_open_remedial_action()
        milestone_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

        assert_score(report["attainment_score"], 0.2727)
        assert report["compliance_status"] == "FAIL", (
            f"a 0.2727 score below 0.85 is a FAIL, got {report['compliance_status']}"
        )
        assert report["failed_standard_codes"] == [
            "HYDROPERIOD_DAYS",
            "INVASIVE_COVER_PCT",
        ], f"both year-1 standards were missed, got {report['failed_standard_codes']}"

        assert action["status"] == "OPEN", f"the action opens OPEN, got {action['status']}"
        assert action["round_number"] == 1, f"round 1, got {action['round_number']}"
        assert_credits(action["held_credits"], 14.82, "held_credits")
        assert action["due_at"].startswith("2028-09-14T00:00:00"), (
            f"due_at is the 2027-09-15 clock plus 365 days, got {action['due_at']}"
        )
        assert action["corrective_scope"] == (
            "REMEDIATE: HYDROPERIOD_DAYS,INVASIVE_COVER_PCT"
        ), f"corrective_scope: {action['corrective_scope']}"
        assert action["deferred_milestone_id"] == milestone_id, (
            "the action records the milestone it froze"
        )

        for round_index in range(3):
            submit_remedial_work(world, action["id"])
            inspect_remedial_action(world, action["id"], "NOT_CLEARED", member_index=2)
            milestone = milestone_state(milestone_id, world)
            assert milestone["status"] == "DEFERRED", (
                f"pass {round_index + 1}: the milestone stays DEFERRED, "
                f"got {milestone['status']}"
            )
            bank = bank_state(world)
            assert_credits(bank["credits_on_hold"], 14.82, "credits_on_hold")
            assert_credits(bank["credits_available"], 0.00, "credits_available")
            assert_credit_conservation(bank)

        entries = ledger_rows(world)
        assert_ledger_sequence(entries)
        assert_ledger_shape(
            entries,
            [
                ("GENERATED", 0.00, 0.00),
                ("RELEASED", 14.82, 14.82),
                ("HOLD_PLACED", -14.82, 0.00),
            ],
        )
        holds_placed = [e for e in entries if e["entry_type"] == "HOLD_PLACED"]
        assert len(holds_placed) == 1, (
            f"the reinspection cycle appends no further hold, got {len(holds_placed)}"
        )
        assert holds_placed[0]["source_entity_type"] == "REMEDIAL_ACTION", (
            "the freeze is attributed to the remedial action, got "
            f"{holds_placed[0]['source_entity_type']}"
        )
        assert holds_placed[0]["source_id"] == action["id"], (
            "the freeze names the remedial action that placed it"
        )


class TestFailingReviewCascade:
    """One ACCEPT with a FAIL score drives the whole failure chain."""

    def test_failing_year_three_acceptance_opens_the_action_and_restricts_the_posture(self):
        """Hops one to three: the report's ecological dimension becomes FAIL, a
        round-1 remedial action is created against it, and the bank's posture is
        recomputed to RESTRICTED because that action is non-terminal.

        PRD §3.7: "And if the computed compliance status is `FAIL`, acceptance triggers a four-hop cascade whose order is pinned, because the credit arithmetic at the end depends on it."
        PRD §3.7: "The first hop creates a remedial action against this report. It opens in `OPEN` status with `round_number` at 1, its `monitoring_report_id` naming the failing report, its `opened_at` stamped with the logical clock, its `due_at` set to that clock plus 365 days, and its `corrective_scope` auto-generated as the literal text `REMEDIATE: ` followed by the failed standard codes joined by commas in the same ascending order they were listed in."
        PRD §3.7: "The second hop recomputes the bank's posture, which now finds a non-terminal remedial action and therefore lands on `RESTRICTED`."
        Design: Difficulty/transitive_cascade/failed_year3_review_cascades_five_hops_to_sale_cancellation
        """
        world, _sale, report = _world_with_reserved_sale_and_failing_year3_report()

        accepted = review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)
        assert accepted["review_status"] == "ACCEPTED", (
            f"the paperwork dimension reaches ACCEPTED, got {accepted['review_status']}"
        )
        assert_score(accepted["attainment_score"], 0.6150)
        assert accepted["compliance_status"] == "FAIL", (
            f"a 0.6150 score below 0.85 is a FAIL, got {accepted['compliance_status']}"
        )
        assert accepted["failed_standard_codes"] == [
            "HYDROPERIOD_DAYS",
            "INVASIVE_COVER_PCT",
            "NATIVE_COVER_PCT",
        ], f"three standards were missed, got {accepted['failed_standard_codes']}"

        actions = remedial_actions_for_report(world, report["id"])
        assert len(actions) == 1, (
            f"the cascade creates exactly one remedial action, got {len(actions)}"
        )
        action = actions[0]
        assert action["status"] == "OPEN", f"the action opens OPEN, got {action['status']}"
        assert action["round_number"] == 1, f"round 1, got {action['round_number']}"
        assert action["monitoring_report_id"] == report["id"], (
            "the action names the failing report"
        )
        assert_credits(action["held_credits"], 14.82, "held_credits")
        assert action["due_at"].startswith("2030-09-05T00:00:00"), (
            f"due_at is the 2029-09-05 clock plus 365 days, got {action['due_at']}"
        )
        assert action["corrective_scope"] == (
            "REMEDIATE: HYDROPERIOD_DAYS,INVASIVE_COVER_PCT,NATIVE_COVER_PCT"
        ), f"corrective_scope: {action['corrective_scope']}"

        bank = bank_state(world)
        assert bank["sales_posture"] == "RESTRICTED", (
            "a non-terminal remedial action outranks the SOLD_OUT branch, got "
            f"{bank['sales_posture']}"
        )

    def test_failing_year_three_acceptance_cancels_the_hold_then_defers_the_milestone(self):
        """Hops four and five: because the posture went RESTRICTED the reserved
        sale is cancelled and its hold returned, and only then is the earliest
        non-terminal milestone deferred.

        PRD §3.7: "The third hop acts on that posture change: every credit sale of the bank standing in `QUOTED` or `RESERVED` is cancelled with a `cancelled_reason` of `BANK_POSTURE_RESTRICTED` and a `cancelled_at` stamp, and each formerly reserved sale appends a `HOLD_RELEASED` entry that restores its held credits to the bank's available pool."
        PRD §3.7: "The fourth hop defers a milestone: the bank's earliest non-terminal release milestone, ordered by window start ascending with creation order as the tie-break, transitions to `DEFERRED` with `deferred_at` stamped, and the bank's `deferral_count` rises by one."
        PRD §3.7: "If the bank has never had an accepted report before, this acceptance additionally carries the bank `INSTRUMENT_EXECUTED → MONITORING`."
        Design: Difficulty/transitive_cascade/failed_year3_review_cascades_five_hops_to_sale_cancellation
        """
        world, sale, report = _world_with_reserved_sale_and_failing_year3_report()
        milestone_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

        review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)

        cancelled = sale_state(sale["id"], world)
        assert cancelled["status"] == "CANCELLED", (
            f"a RESERVED sale is withdrawn by the restriction, got {cancelled['status']}"
        )
        assert cancelled["cancelled_reason"] == "BANK_POSTURE_RESTRICTED", (
            f"cancelled_reason: {cancelled['cancelled_reason']}"
        )
        assert cancelled["cancelled_at"].startswith("2029-09-05T00:00:00"), (
            f"cancelled_at is stamped from the clock, got {cancelled['cancelled_at']}"
        )

        milestone = milestone_state(milestone_id, world)
        assert milestone["status"] == "DEFERRED", (
            "the earliest non-terminal milestone is deferred, got "
            f"{milestone['status']}"
        )
        assert milestone["deferred_at"].startswith("2029-09-05T00:00:00"), (
            f"deferred_at is stamped from the clock, got {milestone['deferred_at']}"
        )

        bank = bank_state(world)
        assert bank["deferral_count"] == 1, (
            f"deferral_count rises by one, got {bank['deferral_count']}"
        )
        assert bank["status"] == "MONITORING", (
            "the first accepted report still moves the bank out of INSTRUMENT_EXECUTED "
            f"even though it failed, got {bank['status']}"
        )
        assert bank["open_quote_count"] == 0, (
            f"the cancelled sale leaves the quote tally, got {bank['open_quote_count']}"
        )

    def test_five_hop_cascade_appends_its_ledger_rows_in_the_pinned_order(self):
        """Releasing the sale's 4.00-credit hold before freezing the unsold
        14.82 credits is what keeps every running balance non-negative, and the
        five rows carry the pinned balances 0.00, 14.82, 10.82, 14.82, 0.00.

        PRD §2.11: "When a single request appends more than one entry, the order in which this document pins those appends determines their `sequence_number` values, and therefore also their running balances."
        PRD §2.11: "`balance_after` records the bank's available credits immediately after the entry was appended, and is therefore the running accumulation of every `delta_credits` from sequence number 1 through this entry inclusive."
        PRD §3.7: "The remedial action's `deferred_milestone_id` records which milestone it froze, and its `held_credits` is evaluated *at this point in the chain* — that is, after the third hop has already returned the cancelled reservations' credits — as the bank's released credits minus its sold credits."
        PRD §2.11: "The invariant no endpoint may ever break is that released credits equal the sum of sold, on-hold and available credits, and that available credits equal the `balance_after` of the bank's highest-numbered ledger entry."
        Design: Difficulty/transitive_cascade/failed_year3_review_cascades_five_hops_to_sale_cancellation
        """
        world, _sale, report = _world_with_reserved_sale_and_failing_year3_report()
        review_monitoring_report(world, report["id"], "ACCEPT", member_index=1)

        entries = ledger_rows(world)
        assert_ledger_sequence(entries)
        assert_ledger_shape(
            entries,
            [
                ("GENERATED", 0.00, 0.00),
                ("RELEASED", 14.82, 14.82),
                ("HOLD_PLACED", -4.00, 10.82),
                ("HOLD_RELEASED", 4.00, 14.82),
                ("HOLD_PLACED", -14.82, 0.00),
            ],
        )
        for entry in entries:
            assert entry["balance_after"] >= 0, (
                f"row {entry['sequence_number']} ({entry['entry_type']}) drove the "
                f"balance negative at {entry['balance_after']}"
            )

        bank = bank_state(world)
        assert_credits(bank["credits_released"], 14.82, "credits_released")
        assert_credits(bank["credits_sold"], 0.00, "credits_sold")
        assert_credits(bank["credits_on_hold"], 14.82, "credits_on_hold")
        assert_credits(bank["credits_available"], 0.00, "credits_available")
        assert_credit_conservation(bank)
        assert_credits(
            bank["credits_available"], entries[-1]["balance_after"], "available vs ledger"
        )


def _world_after_clearance():
    """The failure world of the reinspection tests carried through one round of
    corrective work that the STATE_DEQ seat then verified as CLEARED.

    Returns the world, the remedial action id and the cleared action row.
    """
    world, _report, action = _world_with_open_remedial_action()
    submit_remedial_work(world, action["id"])
    cleared = inspect_remedial_action(world, action["id"], "CLEARED", member_index=2)
    return world, action["id"], cleared


class TestClearedRemedialActionRecovery:
    """The recovery chain: clearance, milestone restoration, availability."""

    def test_clearance_restores_the_claimed_milestone_and_the_frozen_credits(self):
        """All three recovery hops in one request: the action clears, the
        deferred milestone returns to CLAIMED rather than PENDING because it had
        been claimed before the deferral, and the 14.82-credit hold is released
        so the posture recomputes to OPEN.

        PRD §3.7: "An outcome of `CLEARED` advances the action `REINSPECTION → CLEARED`, records the acting member into `verified_by_member_id` and stamps `cleared_at`; that recorded member is precisely the person who may never afterwards approve the release of the milestone this action deferred."
        PRD §3.7: "Because no non-terminal remedial action remains for the bank, the deferred milestone is restored: `DEFERRED → CLAIMED` when it had been claimed before it was deferred, and `DEFERRED → PENDING` when it had not, with a `HOLD_RELEASED` entry appended — again attributed to the remedial action — carrying the previously held quantity as a positive delta, and again only when that quantity is greater than zero."
        PRD §3.7: "The bank's credits on hold and available credits are recomputed, the posture is recomputed back to `OPEN`, a bank sitting in `SUSPENDED` returns to `MONITORING`, the owning sponsor's `good_standing` is recomputed to true unless another of its banks is still suspended, and the bank's `version` increments by one."
        Design: Difficulty/transitive_cascade/cleared_remedial_action_cascades_three_hops_restoring_availability
        """
        world, action_id, cleared = _world_after_clearance()
        milestone_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

        assert cleared["status"] == "CLEARED", (
            f"a CLEARED outcome resolves the action, got {cleared['status']}"
        )
        assert cleared["cleared_at"].startswith("2027-09-15T00:00:00"), (
            f"cleared_at is stamped from the clock, got {cleared['cleared_at']}"
        )
        assert cleared["verified_by_member_id"] == world["members"][2]["id"], (
            "the inspecting member is recorded as the verifier"
        )
        assert remedial_action_state(action_id, world)["status"] == "CLEARED", (
            "the cleared action reads back as CLEARED"
        )

        milestone = milestone_state(milestone_id, world)
        assert milestone["status"] == "CLAIMED", (
            "a milestone claimed before its deferral returns to CLAIMED, got "
            f"{milestone['status']}"
        )
        assert milestone["claimed_at"] is not None, (
            "the original claim timestamp survives the deferral"
        )

        bank = bank_state(world)
        assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
        assert_credits(bank["credits_available"], 14.82, "credits_available")
        assert bank["sales_posture"] == "OPEN", (
            "with no non-terminal action left the posture returns to OPEN, got "
            f"{bank['sales_posture']}"
        )
        assert bank["status"] == "MONITORING", (
            f"the bank was never suspended, so it stays in MONITORING, got {bank['status']}"
        )
        assert_credit_conservation(bank)

        entries = ledger_rows(world)
        assert_ledger_sequence(entries)
        assert_ledger_shape(
            entries,
            [
                ("GENERATED", 0.00, 0.00),
                ("RELEASED", 14.82, 14.82),
                ("HOLD_PLACED", -14.82, 0.00),
                ("HOLD_RELEASED", 14.82, 14.82),
            ],
        )
        released_holds = [e for e in entries if e["entry_type"] == "HOLD_RELEASED"]
        assert len(released_holds) == 1, (
            f"the hold is released exactly once, got {len(released_holds)}"
        )
        assert released_holds[0]["source_entity_type"] == "REMEDIAL_ACTION", (
            "the release is attributed to the remedial action, got "
            f"{released_holds[0]['source_entity_type']}"
        )
        assert released_holds[0]["source_id"] == action_id, (
            "the release names the remedial action that had frozen the credits"
        )

    def test_recovery_release_by_a_different_member_frees_the_second_tranche(self):
        """Once the recovery has restored availability, a member other than the
        verifier may approve the restored milestone: CONSTRUCTION_COMPLETE
        consults no monitoring, so its 19.75-credit tranche is released in full.

        PRD §3.6: "For the two construction milestones, `INSTRUMENT_EXECUTION` and `CONSTRUCTION_COMPLETE`, no monitoring is consulted at all and the attainment factor is exactly 1.00 — earthwork needs no growing season."
        PRD §3.6: "The final release quantity is then the *already-rounded* provisional quantity multiplied by the selected factor, rounded half up to 2 decimal places again."
        PRD §3.6: "A ledger entry of type `RELEASED` is appended carrying the final release quantity as a positive delta, attributed through a source entity type of `RELEASE_MILESTONE` and the milestone's own identifier, with a memo naming the release, its milestone code and the attainment factor applied."
        Design: Difficulty/transitive_cascade/cleared_remedial_action_cascades_three_hops_restoring_availability
        """
        world, _action_id, _cleared = _world_after_clearance()
        milestone_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]

        approved = get_success_data(
            api_client.approve_milestone_release(
                milestone_id,
                approve_release_payload(bank_version(world)),
                world["member_headers"][0],
            )
        )
        assert approved["status"] == "APPROVED", (
            f"the restored milestone releases its tranche, got {approved['status']}"
        )
        assert_credits(approved["attainment_factor_applied"], 1.00, "attainment_factor_applied")
        assert_credits(approved["final_release_credits"], 19.75, "final_release_credits")

        bank = bank_state(world)
        assert_credits(bank["credits_released"], 34.57, "credits_released")
        assert_credits(bank["credits_available"], 34.57, "credits_available")
        assert_credits(bank["credits_on_hold"], 0.00, "credits_on_hold")
        assert_credit_conservation(bank)

        entries = ledger_rows(world)
        assert_ledger_sequence(entries)
        assert_ledger_shape(
            entries,
            [
                ("GENERATED", 0.00, 0.00),
                ("RELEASED", 14.82, 14.82),
                ("HOLD_PLACED", -14.82, 0.00),
                ("HOLD_RELEASED", 14.82, 14.82),
                ("RELEASED", 19.75, 34.57),
            ],
        )
        assert entries[-1]["source_entity_type"] == "RELEASE_MILESTONE", (
            "the release is attributed to the milestone, got "
            f"{entries[-1]['source_entity_type']}"
        )
        assert entries[-1]["source_id"] == milestone_id, (
            "the release names the milestone that produced it"
        )

        sponsor = get_success_data(
            api_client.get_sponsor(world["sponsor"]["id"], world["sponsor_headers"])
        )
        assert sponsor["good_standing"] is True, (
            "the bank was never suspended, so the sponsor never left good standing"
        )

    def test_the_clearance_verifier_may_never_approve_the_release_it_deferred(self):
        """The member recorded as verifying the clearance is permanently barred
        from approving the very milestone that action had deferred, so the
        recovery must be finished by a different seat.

        PRD §2.1: "And the member who verified the clearing reinspection of a remedial action may never be the member who approves the release of the milestone that action had deferred — an attempt is rejected with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."
        Design: Difficulty/transitive_cascade/cleared_remedial_action_cascades_three_hops_restoring_availability
        """
        world, _action_id, cleared = _world_after_clearance()
        milestone_id = world["milestones"]["CONSTRUCTION_COMPLETE"]["id"]
        assert cleared["verified_by_member_id"] == world["members"][2]["id"], (
            "the STATE_DEQ seat verified the clearance"
        )

        response = api_client.approve_milestone_release(
            milestone_id,
            approve_release_payload(bank_version(world)),
            world["member_headers"][2],
        )
        validate_error(response, ApiErrorId.ERR_SEGREGATION_OF_DUTIES, 403)

        milestone = milestone_state(milestone_id, world)
        assert milestone["status"] == "CLAIMED", (
            f"the rejected approval leaves the milestone CLAIMED, got {milestone['status']}"
        )
        bank = bank_state(world)
        assert_credits(bank["credits_released"], 14.82, "credits_released")
        assert_credit_conservation(bank)
