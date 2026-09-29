"""Declared edges, refused edges and the cascades a legal edge drags behind it."""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import api_errors as e
from test_helpers import fixtures as fx
from test_helpers import test_users as users
from test_helpers.api_client import ApiClient
from test_helpers.assertions import (
    assert_cents,
    assert_field_sequence,
    assert_fields,
    assert_null_fields,
    assert_page,
    assert_score,
)

SECOND_BID_RATES = {
    "cement_per_sack_cents": 4500,
    "rig_day_rate_cents": 800000,
    "casing_per_ft_cents": 1500,
    "mobilization_fee_cents": 2200000,
}
THIRD_BID_RATES = {
    "cement_per_sack_cents": 5000,
    "rig_day_rate_cents": 700000,
    "casing_per_ft_cents": 1600,
    "mobilization_fee_cents": 2000000,
}


def test_every_freshly_created_row_sits_in_its_declared_initial_state(api: ApiClient):
    """Seven new rows land on their opening state with their cycle counters at zero.

    The two dimensions of a well move independently, so opening a determination on one
    well reclassifies its lifecycle without touching its access dimension, while a notice
    request on another moves the access dimension and leaves the lifecycle alone.

    PRD: "The new row starts in `DRAFT` with `revision_round` 0, records the acting
    `X-User-ID` as `created_by_user_id`, and leaves `decided_by_user_id`,
    `decision_rationale`, `submitted_at`, `decided_at` and the three snapshot fields
    null."

    Design: Corner/state_machines/newly_created_rows_start_in_their_declared_initial_states
    """
    releasing = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    receiving = fx.make_operator(api, name="Wasatch Acquisition Co", region_code="WY")
    noticed = fx.make_well(api, releasing["id"])
    classified = fx.make_well(api, releasing["id"], spud_year=1976)

    determination = fx.open_determination(
        api, classified["id"], inspector_notes="no operator response to inspection notice"
    )
    access = fx.open_site_access(
        api, noticed["id"], mode="STATUTORY_ENTRY", waiting_period_days=30
    )
    transfer = fx.transfer_well(api, noticed["id"], receiving["id"])
    contractor = fx.make_contractor(api)
    solicitation = fx.make_solicitation(api)
    source = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2027-06-30T00:00:00Z",
        federal_match_required_pct=40,
    )
    report = fx.make_grant_report(api, source["id"], "2026-08-01", "2026-08-31")

    assert_fields(fx.read_operator(api, receiving["id"]), status="ACTIVE")
    assert_fields(
        fx.read_well(api, noticed["id"]),
        status="PRODUCING",
        access_status="ACCESS_PENDING",
    )
    assert_fields(
        fx.read_well(api, classified["id"]),
        status="INACTIVE",
        access_status="NO_ACCESS_REQUESTED",
    )
    assert_fields(determination, status="DRAFT", revision_round=0, version=1)
    assert_null_fields(
        determination,
        "submitted_at",
        "decided_at",
        "decided_by_user_id",
        "decision_rationale",
        "snapshot_idle_months",
        "snapshot_cumulative_boe_60mo",
        "snapshot_screening_score",
    )
    assert_fields(access, status="REQUESTED")
    assert_null_fields(access, "resolved_at")
    assert_fields(transfer, status="PENDING")
    assert_null_fields(transfer, "approved_at", "voided_at", "void_reason")
    assert_fields(contractor, license_status="GOOD_STANDING")
    assert_null_fields(contractor, "suspended_at")
    assert_fields(solicitation, status="DRAFT", reopen_round=0)
    assert_fields(source, status="ACTIVE", reporting_required=True)
    assert_cents(source["committed_cents"], 0, "committed_cents")
    assert_fields(report, status="DUE", revision_round=0, wells_plugged_count=0)
    assert_cents(report["reported_cost_cents"], 0, "reported_cost_cents")
    assert_score(report["federal_share_pct"], 0.00, "federal_share_pct")
    assert_null_fields(report, "submitted_by_user_id", "reviewer_note")


def test_a_decision_aimed_at_a_draft_determination_is_not_an_edge(api: ApiClient):
    """Confirming a case that was never submitted is refused as an undeclared move.

    Nothing at all is written: the determination keeps its empty decision fields and its
    null snapshots, and the well never leaves the state the authoring call put it in.

    PRD: "`CONFIRMED`, `REJECTED` and `SUPERSEDED` are all terminal: no action moves a
    determination out of them, and an attempt reports `ERR_INVALID_STATE_TRANSITION`. A
    decision aimed at a determination still in `DRAFT` reports the same error."

    Design: Corner/state_machines/decision_on_a_draft_determination_is_rejected_as_invalid_transition
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(api, operator["id"])
    determination = fx.open_determination(api, well["id"])

    validate_error(
        api.decide_orphan_determination(
            determination["id"],
            {"action": "CONFIRM", "rationale": "premature confirmation attempt"},
            users.REVIEWER,
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    stored = fx.read_determination(api, determination["id"])
    assert_fields(stored, status="DRAFT")
    assert_null_fields(
        stored, "decided_by_user_id", "decided_at", "snapshot_screening_score"
    )
    refreshed = fx.read_well(api, well["id"])
    assert_fields(refreshed, status="INACTIVE")
    assert_null_fields(refreshed, "orphan_confirmed_at")
    assert_fields(fx.read_operator(api, operator["id"]), orphan_candidate_count=0)


def test_submitting_an_already_submitted_determination_is_refused(api: ApiClient):
    """There is no submit edge out of the submitted state, so the repeat call fails.

    The first submission's timestamp and frozen snapshots survive untouched, and the
    revised narrative the rejected call carried is not stored.

    PRD: "Submission is legal only from `DRAFT` or from `REVISION_REQUESTED`, and only
    for the author: the acting `X-User-ID` must equal `created_by_user_id`."

    Design: Corner/state_machines/second_submit_on_an_already_submitted_determination_is_rejected
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(api, operator["id"])
    determination = fx.open_determination(api, well["id"])
    fx.submit_determination(api, determination["id"])

    validate_error(
        api.submit_orphan_determination(
            determination["id"],
            users.INSPECTOR,
            {"inspector_notes": "resubmitting the same package"},
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    stored = fx.read_determination(api, determination["id"])
    assert_fields(
        stored,
        status="SUBMITTED",
        submitted_at="2026-08-01T00:00:00Z",
        snapshot_idle_months=999,
        inspector_notes="orphan candidate",
    )
    assert_score(
        stored["snapshot_screening_score"], 59.90, "snapshot_screening_score"
    )
    assert_fields(fx.read_well(api, well["id"]), status="ORPHAN_CANDIDATE")


def test_terminal_rows_refuse_every_further_move_and_keep_their_cascades(api: ApiClient):
    """A confirmed determination and a cancelled solicitation are both closed for good.

    Two independent machines are pushed at once, one by a second reviewer and one by a
    reopen, and both refuse; the confirmation's decider and the well's confirmed stamp
    survive, and so does the cancelled bid's outcome.

    PRD: "`CONFIRMED`, `REJECTED` and `SUPERSEDED` are all terminal: no action moves a
    determination out of them, and an attempt reports `ERR_INVALID_STATE_TRANSITION`."

    Design: Corner/state_machines/terminal_states_reject_every_further_transition
    """
    orphan = fx.make_confirmed_orphan_well(api)
    contractor = fx.make_contractor(api)
    solicitation = fx.make_open_solicitation(api)
    bid = fx.place_bid(api, solicitation["id"], contractor["id"])
    fx.advance_solicitation(api, solicitation["id"], "CANCEL")

    validate_error(
        api.decide_orphan_determination(
            orphan["determination"]["id"],
            {"action": "REJECT", "rationale": "reversing the confirmation"},
            users.REVIEWER_2,
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )
    validate_error(
        api.solicitation_lifecycle(
            solicitation["id"],
            {"action": "REOPEN", "new_bid_due_at": "2026-08-25T00:00:00Z"},
            users.PROCUREMENT,
        ),
        e.ERR_INVALID_STATE_TRANSITION,
        409,
    )

    assert_fields(
        fx.read_determination(api, orphan["determination"]["id"]),
        status="CONFIRMED",
        decided_by_user_id="u_rev",
    )
    assert_fields(
        fx.read_well(api, orphan["well"]["id"]),
        status="ORPHAN_CONFIRMED",
        orphan_confirmed_at="2026-08-01T00:00:00Z",
    )
    assert_fields(
        fx.read_solicitation(api, solicitation["id"]),
        status="CANCELLED",
        reopen_round=0,
    )
    assert_fields(fx.read_bid(api, bid["id"]), status="NOT_AWARDED")


def test_entry_may_be_ordered_at_the_very_instant_the_window_closes(api: ApiClient):
    """The waiting window is over the moment the clock reaches its end, not after it.

    One call at exactly 2026-08-31T00:00:00Z fires all four consequences at once, and the
    well's lifecycle dimension is deliberately left where it was: only the access
    dimension moves.

    PRD: "The clock standing exactly at `window_end_at` is sufficient, because the notice
    window is closed and has therefore fully elapsed at that instant."

    Design: Corner/state_machines/ordering_statutory_entry_after_the_notice_window_updates_both_rows
    """
    operator = fx.make_operator(api, name="Cottonwood Energy LLC", region_code="WY")
    well = fx.make_well(api, operator["id"])
    access = fx.open_site_access(
        api,
        well["id"],
        mode="STATUTORY_ENTRY",
        waiting_period_days=30,
        compensation_cents=250000,
    )
    assert_fields(
        access,
        status="REQUESTED",
        notice_sent_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-31T00:00:00Z",
    )
    fx.set_clock(api, "2026-08-31T00:00:00Z")

    ordered = fx.resolve_site_access(
        api, access["id"], "ORDER_ENTRY", "W.S. 30-5-104(d)(vi)"
    )
    assert_fields(
        ordered,
        status="ENTRY_ORDERED",
        legal_authority_citation="W.S. 30-5-104(d)(vi)",
        resolved_at="2026-08-31T00:00:00Z",
        notice_sent_at="2026-08-01T00:00:00Z",
        window_end_at="2026-08-31T00:00:00Z",
    )
    assert_cents(ordered["compensation_cents"], 250000, "compensation_cents")

    assert_fields(
        fx.read_well(api, well["id"]),
        access_status="ENTRY_ORDERED",
        status="PRODUCING",
    )


def test_cancelling_sweeps_bids_out_of_all_three_live_states_at_once(api: ApiClient):
    """One cancellation closes a submitted, a responsive and a nonresponsive bid.

    The sweep reaches all three live states in a single call and reaches them from the
    evaluating stage rather than from the open one, the recorded reason for the
    nonresponsive bid is carried through untouched, and no contract is born.

    PRD: "Cancelling is available from `DRAFT`, from `OPEN` and from `EVALUATING`, moves
    the row to `CANCELLED`, and sweeps the bid field clean: every bid on this solicitation
    whose `status` is `SUBMITTED`, `RESPONSIVE` or `NONRESPONSIVE` transitions to
    `NOT_AWARDED` without any score being computed, each with its own `version`
    incremented."

    Design: Corner/state_machines/cancelling_a_solicitation_marks_every_unawarded_bid_not_awarded
    """
    first = fx.make_contractor(api, name="Bighorn Plugging", license_number="P-11077")
    second = fx.make_contractor(
        api, name="Laramie Well Services", license_number="P-11078", performance_score=84
    )
    third = fx.make_contractor(
        api,
        name="Sweetwater Abandonment",
        license_number="P-11079",
        performance_score=77,
    )
    solicitation = fx.make_open_solicitation(
        api, scope_description="regional plugging program"
    )
    submitted = fx.place_bid(api, solicitation["id"], first["id"])
    responsive = fx.place_bid(
        api,
        solicitation["id"],
        second["id"],
        rates=SECOND_BID_RATES,
        technical_score=80,
    )
    nonresponsive = fx.place_bid(
        api,
        solicitation["id"],
        third["id"],
        rates=THIRD_BID_RATES,
        technical_score=75,
    )
    fx.advance_solicitation(api, solicitation["id"], "CLOSE")
    fx.evaluate_bid(api, responsive["id"], "RESPONSIVE")
    fx.evaluate_bid(
        api,
        nonresponsive["id"],
        "NONRESPONSIVE",
        reason="no bonding evidence attached",
    )

    cancelled = fx.advance_solicitation(api, solicitation["id"], "CANCEL")
    assert_fields(cancelled, status="CANCELLED")

    assert_fields(fx.read_bid(api, submitted["id"]), status="NOT_AWARDED")
    assert_fields(fx.read_bid(api, responsive["id"]), status="NOT_AWARDED")
    assert_fields(
        fx.read_bid(api, nonresponsive["id"]),
        status="NOT_AWARDED",
        nonresponsive_reason="no bonding evidence attached",
    )
    assert_page(api.list_unit_cost_contracts(users.PROCUREMENT), 0, expected_total=0)


def test_reopening_returns_the_solicitation_to_open_with_a_fresh_deadline(api: ApiClient):
    """The procurement machine is a cycle, so a thin field can be reopened for bidders.

    Reopening is available while no bid stands responsive, and it counts the round,
    replaces the deadline, leaves the evaluation already recorded against the first bid
    alone, and lets a late bidder join with its own computed unit cost.

    PRD: "it is permitted only while the count of this solicitation's bids in `RESPONSIVE`
    status is exactly zero, only while `reopen_round` is still below the ceiling of 1
    completed reopen cycle, and only when `new_bid_due_at` is supplied and is strictly
    after the logical clock. A successful reopen increments `reopen_round` by one and
    replaces `bid_due_at` with `new_bid_due_at`."

    Design: Corner/state_machines/reopening_a_solicitation_returns_it_to_open_with_a_new_deadline
    """
    first = fx.make_contractor(api, name="Bighorn Plugging", license_number="P-11077")
    second = fx.make_contractor(
        api, name="Laramie Well Services", license_number="P-11078", performance_score=84
    )
    solicitation = fx.make_open_solicitation(
        api, scope_description="regional plugging program"
    )
    early = fx.place_bid(api, solicitation["id"], first["id"])
    fx.advance_solicitation(api, solicitation["id"], "CLOSE")
    fx.evaluate_bid(
        api, early["id"], "NONRESPONSIVE", reason="unit rates missing a cement addendum"
    )

    reopened = fx.advance_solicitation(
        api, solicitation["id"], "REOPEN", new_bid_due_at="2026-08-28T00:00:00Z"
    )
    assert_fields(
        reopened, status="OPEN", reopen_round=1, bid_due_at="2026-08-28T00:00:00Z"
    )

    late = fx.place_bid(
        api,
        solicitation["id"],
        second["id"],
        rates=SECOND_BID_RATES,
        technical_score=80,
    )
    assert_fields(late, status="SUBMITTED")
    assert_cents(
        late["evaluated_unit_cost_cents"], 7140000, "evaluated_unit_cost_cents"
    )
    assert_fields(
        fx.read_bid(api, early["id"]),
        status="NONRESPONSIVE",
        nonresponsive_reason="unit rates missing a cement addendum",
    )


def test_responsiveness_can_be_flipped_back_and_forth_on_the_same_bid(api: ApiClient):
    """Three evaluations in a row walk one bid responsive, nonresponsive and back again.

    Each pass rewrites who evaluated it, the reason recorded on the way down is cleared
    on the way back up, and the computed unit cost never moves because responsiveness is
    a judgement about paperwork rather than about price.

    PRD: "The pair therefore cycles freely - `RESPONSIVE → NONRESPONSIVE →
    RESPONSIVE` is entirely legal right up until the solicitation is awarded."

    Design: Corner/state_machines/bid_reevaluation_flips_responsiveness_in_both_directions
    """
    contractor = fx.make_contractor(api, name="Bighorn Plugging", license_number="P-11077")
    solicitation = fx.make_open_solicitation(
        api, scope_description="regional plugging program"
    )
    bid = fx.place_bid(api, solicitation["id"], contractor["id"])
    fx.advance_solicitation(api, solicitation["id"], "CLOSE")

    responsive = fx.evaluate_bid(api, bid["id"], "RESPONSIVE")
    assert_fields(responsive, status="RESPONSIVE", evaluated_by_user_id="u_proc")

    rejected = validate_success(
        api.evaluate_bid(
            bid["id"],
            {
                "outcome": "NONRESPONSIVE",
                "reason": "unit rates missing a cement addendum",
            },
            users.PROCUREMENT_2,
        ),
        200,
    )
    assert_fields(
        rejected,
        status="NONRESPONSIVE",
        nonresponsive_reason="unit rates missing a cement addendum",
        evaluated_by_user_id="u_proc2",
    )

    restored = validate_success(
        api.evaluate_bid(bid["id"], {"outcome": "RESPONSIVE"}, users.PROCUREMENT_3),
        200,
    )
    assert_fields(restored, status="RESPONSIVE", evaluated_by_user_id="u_proc3")
    assert_null_fields(restored, "nonresponsive_reason", "composite_score", "price_score")
    for stage in (responsive, rejected, restored):
        assert_cents(
            stage["evaluated_unit_cost_cents"], 7366835, "evaluated_unit_cost_cents"
        )


def test_a_licence_suspension_and_its_reversal_both_reach_the_contract(api: ApiClient):
    """The contract has no endpoint of its own, so licensing drives it in both directions.

    Suspending the contractor drives its live contract to suspended and reinstating drives
    it back, while the four negotiated unit rates, the ceiling, the obligation figure and
    the award provenance are all left exactly as the award wrote them.

    PRD: "Suspending a licence is available only from `GOOD_STANDING`: it sets
    `license_status` to `SUSPENDED`, stamps `suspended_at` with the logical clock, and
    cascades to every unit-cost contract of this contractor whose `status` is `ACTIVE`,
    moving each one `ACTIVE → SUSPENDED` and incrementing its `version`."

    Design: Corner/state_machines/contractor_suspension_and_reinstatement_cascade_contracts_both_ways
    """
    contractor = fx.make_contractor(api, name="Bighorn Plugging", license_number="P-11077")
    procurement = fx.make_active_contract(
        api, contractor=contractor, scope_description="single orphan well plugging"
    )
    contract_id = procurement["contract"]["id"]

    def assert_commercial_terms_survived(contract):
        assert_fields(
            contract,
            winning_bid_id=procurement["bid"]["id"],
            awarded_by_user_id="u_award",
        )
        assert_cents(contract["cement_per_sack_cents"], 4137, "cement_per_sack_cents")
        assert_cents(contract["rig_day_rate_cents"], 849999, "rig_day_rate_cents")
        assert_cents(contract["casing_per_ft_cents"], 1213, "casing_per_ft_cents")
        assert_cents(contract["mobilization_fee_cents"], 2499999, "mobilization_fee_cents")
        assert_cents(contract["ceiling_cents"], 20000000, "ceiling_cents")
        assert_cents(contract["obligated_cents"], 0, "obligated_cents")

    assert_commercial_terms_survived(procurement["contract"])

    suspended = fx.set_license_status(
        api, contractor["id"], "SUSPEND_LICENSE", "expired insurance certificate"
    )
    assert_fields(
        suspended, license_status="SUSPENDED", suspended_at="2026-08-01T00:00:00Z"
    )
    under_suspension = fx.read_contract(api, contract_id)
    assert_fields(under_suspension, status="SUSPENDED")
    assert_commercial_terms_survived(under_suspension)

    reinstated = fx.set_license_status(
        api, contractor["id"], "REINSTATE", "insurance certificate refiled"
    )
    assert_fields(reinstated, license_status="GOOD_STANDING")
    assert_null_fields(reinstated, "suspended_at")
    restored = fx.read_contract(api, contract_id)
    assert_fields(restored, status="ACTIVE")
    assert_commercial_terms_survived(restored)


def test_the_third_reclamation_pass_bubbles_the_job_and_the_well_upward(api: ApiClient):
    """Nothing reclaims a job directly; the last surface task does it from below.

    Two of the three tasks passing leaves the job plugged and unreclaimed, and the
    revegetation pass, legal only ninety days after the pit was closed, flips the task,
    the job, the well and the operator's whole exposure in a single call.

    PRD: "The job transitions `PLUGGED → RECLAIMED` and `reclaimed_at` is stamped from
    the logical clock. The well transitions `PLUGGED → RECLAIMED`, which is its terminal
    lifecycle state."

    Design: Corner/state_machines/third_reclamation_pass_bubbles_the_job_and_the_well_to_reclaimed
    """
    bundle = fx.make_plugged_job(api)
    job_id = bundle["job"]["id"]
    well_id = bundle["well"]["id"]
    operator_id = bundle["operator"]["id"]

    tasks = assert_page(
        api.list_reclamation_tasks(job_id, users.INSPECTOR), 3, expected_total=3
    )
    assert_field_sequence(
        tasks, "task_type", ["EQUIPMENT_REMOVAL", "PIT_CLOSURE", "REVEGETATION"]
    )
    equipment = fx.task_by_type(tasks, "EQUIPMENT_REMOVAL")
    pit = fx.task_by_type(tasks, "PIT_CLOSURE")
    revegetation = fx.task_by_type(tasks, "REVEGETATION")

    fx.complete_task(api, equipment["id"], "site clear of equipment")
    closed_pit = fx.complete_task(api, pit["id"], "reserve pit backfilled and contoured")
    assert_fields(
        closed_pit,
        status="COMPLETE",
        completed_at="2026-08-01T00:00:00Z",
        inspected_by_user_id="u_insp",
    )
    assert_fields(fx.read_job(api, job_id), status="PLUGGED")
    assert_null_fields(fx.read_job(api, job_id), "reclaimed_at")
    assert_fields(fx.read_well(api, well_id), status="PLUGGED")

    fx.set_clock(api, "2026-10-30T00:00:00Z")
    fx.progress_task(api, revegetation["id"], "START", "native seed mix drilled")
    finished = fx.progress_task(
        api, revegetation["id"], "PASS", "70 percent cover established"
    )
    assert_fields(
        finished, status="COMPLETE", completed_at="2026-10-30T00:00:00Z"
    )

    assert_fields(
        fx.read_job(api, job_id),
        status="RECLAIMED",
        reclaimed_at="2026-10-30T00:00:00Z",
    )
    assert_fields(fx.read_well(api, well_id), status="RECLAIMED")
    operator = fx.read_operator(api, operator_id)
    assert_fields(
        operator, active_well_count=0, orphan_candidate_count=0, status="ACTIVE"
    )
    assert_cents(operator["required_bond_cents"], 0, "required_bond_cents")
    for task in assert_page(
        api.list_reclamation_tasks(job_id, users.INSPECTOR), 3, expected_total=3
    ):
        assert_fields(task, status="COMPLETE", inspection_round=0)


def test_moving_the_clock_expires_a_live_source_and_an_exhausted_one(api: ApiClient):
    """Expiry is the clock's own cascade and it reaches both live source states.

    The state fund drained to the cent by the waterfall and the federal grant that the
    waterfall never touched both expire at the boundary instant they name, a source dated
    further out is left alone, and the obligation already committed is not disturbed.

    PRD: "every `FundingSource` whose `expires_at` is at or before the new clock value
    flips from `ACTIVE` or `EXHAUSTED` to `EXPIRED`, and each such source's `version`
    increments."

    Design: Corner/state_machines/clock_advance_expires_active_and_exhausted_funding_sources
    """
    orphan = fx.make_confirmed_orphan_well(api)
    procurement = fx.make_active_contract(
        api, scope_description="single orphan well plugging"
    )
    job = fx.make_plugging_job(
        api,
        orphan["well"]["id"],
        procurement["contract"]["id"],
        scheduled_start="2026-09-01T00:00:00Z",
    )
    federal = fx.make_funding_source(
        api,
        kind="FEDERAL_GRANT",
        name="IIJA orphan well formula grant FY26",
        authorized_cents=10000000,
        expires_at="2026-09-01T00:00:00Z",
        federal_match_required_pct=40,
    )
    expiring = fx.make_funding_source(
        api,
        name="Wyoming orphan well account - expiring appropriation",
        authorized_cents=6070196,
        expires_at="2026-09-01T00:00:00Z",
    )
    carryover = fx.make_funding_source(
        api,
        name="Wyoming orphan well account - biennium carryover",
        authorized_cents=9000000,
        expires_at="2027-12-31T00:00:00Z",
    )
    allocations = fx.commit_funding(api, job["id"])
    assert len(allocations) == 1, (
        "the pass should have drawn on the expiring appropriation alone: %r"
        % (allocations,)
    )

    drained = fx.read_source(api, expiring["id"])
    assert_cents(drained["committed_cents"], 6070196, "committed_cents")
    assert_fields(drained, status="EXHAUSTED")
    untouched = fx.read_source(api, federal["id"])
    assert_cents(untouched["committed_cents"], 0, "federal committed_cents")
    assert_fields(untouched, status="ACTIVE")

    committed = assert_page(
        api.list_funding_allocations(users.FUNDING, {"job_id": job["id"]}),
        1,
        expected_total=1,
    )[0]
    assert_fields(committed, waterfall_rank=2, status="COMMITTED")
    assert_cents(committed["allocated_cents"], 6070196, "allocated_cents")

    fx.set_clock(api, "2026-09-01T00:00:00Z")

    assert_fields(fx.read_source(api, expiring["id"]), status="EXPIRED")
    assert_fields(fx.read_source(api, federal["id"]), status="EXPIRED")
    assert_fields(fx.read_source(api, carryover["id"]), status="ACTIVE")
    assert_fields(fx.read_allocation(api, committed["id"]), status="COMMITTED")
    assert_cents(fx.read_job(api, job["id"])["funded_cents"], 6070196, "funded_cents")
