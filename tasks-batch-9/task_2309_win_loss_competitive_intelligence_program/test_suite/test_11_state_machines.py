"""
Lifecycle edges: initial states, valid steps, refused steps and terminal lockdown.
"""

from prd_bench_local_runner.testing import validate_error, validate_success

from test_helpers import factories as f
from test_helpers.api_errors import (
    ERR_BATTLECARD_STATE_INVALID,
    ERR_INTERVIEW_STATE_INVALID,
    ERR_PROGRAM_STATE_INVALID,
)
from test_helpers.assertions import (
    assert_analyst_workload,
    assert_claim_counters,
    assert_deal_dimensions,
    assert_field,
    assert_fields,
    assert_frame_slots,
    assert_ledger,
    assert_money,
    assert_null,
    assert_ratio,
    assert_risk_indices,
)
from test_helpers.fixtures import WinLossWorld


def _program_with_one_registered_analyst(world: WinLossWorld) -> WinLossWorld:
    """An ACTIVE program plus the ACTIVE analyst whose identity analyst writes need."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_analyst()
    return world


def _drawn_lost_deal(world: WinLossWorld, **program_overrides) -> WinLossWorld:
    """One LOST deal drawn from a sealed frame, with a consenting buyer contact."""
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program(**program_overrides)
    world.create_competitor()
    world.create_analyst()
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    return world


def _card_in_legal_review_with_one_claim_decided(world: WinLossWorld) -> WinLossWorld:
    """A LEGAL_REVIEW card holding an APPROVED LOW claim and a PENDING MEDIUM claim."""
    _drawn_lost_deal(world)
    world.schedule_interview()
    positioning = world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-01T10:05:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    pricing = world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt high for the tier",
        recorded_at="2026-08-01T10:10:00.000Z",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth ranked first",
        recorded_at="2026-08-01T10:15:00.000Z",
    )
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.reference_claim = world.add_claim(
        [positioning["id"]],
        claim_text="Two enterprise buyers referenced our security depth",
        claim_type="REFERENCE",
    )
    world.feature_claim = world.add_claim(
        [pricing["id"]],
        claim_text="Our tiering beats Northwind on price transparency",
        claim_type="FEATURE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE", claim_id=world.reference_claim["id"])
    return world


# ---------------------------------------------------------------------------
# Program and sampling frame
# ---------------------------------------------------------------------------


def test_a_new_sampling_frame_has_no_open_slots_yet(world):
    """Quotas of two, two and one still leave every slot counter at zero.

    "A new frame has `status` `DRAFT` and all slot counters at 0, because open slots
    are not materialised until the frame is sealed."

    Design: Corner/state_machines/sampling_frame_is_born_draft_with_uninitialised_slots
    """
    _program_with_one_registered_analyst(world)

    body = validate_success(
        world.api.create_sampling_frame(
            f.sampling_frame_payload(world.program_id, label="Wave 1"),
            world.analyst_headers,
        ),
        201,
    )
    frame = body

    assert_field(frame, "status", "DRAFT")
    assert_frame_slots(
        frame,
        selected_won=0,
        open_won=0,
        selected_lost=0,
        open_lost=0,
        selected_no_decision=0,
        open_no_decision=0,
        coverage=0.0000,
    )
    assert_field(frame, "version", 1)


def test_activation_lands_active_and_open_on_a_second_version(world):
    """A zero ledger under the ACTIVE floor recomputes to OPEN.

    "Activation recomputes `posture` — with utilization at 0.0000 and an `ACTIVE`
    status floor of `OPEN`, the result is `OPEN` — and increments the program's
    `version`."

    Design: Corner/state_machines/program_activation_from_draft_moves_to_active_and_bumps_version
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    program = world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")

    body = validate_success(
        world.api.activate_program(program["id"], world.admin), 200
    )
    activated = body

    assert_fields(activated, {"status": "ACTIVE", "posture": "OPEN", "version": 2})


def test_closing_a_program_outright_skips_a_step_and_is_refused(world):
    """CLOSED is reachable only from CLOSING, so the shortcut conflicts.

    "The `CLOSING → CLOSED` step requires that no attribution on any of the program's
    deals is still `PROVISIONAL`; it recomputes `posture` under the `CLOSED` floor,
    which forces `FROZEN`, transitions every battlecard of the program's competitors
    whose `status` is `DRAFT`, `LEGAL_REVIEW` or `APPROVED` to `WITHDRAWN`, and
    increments `version`."

    Design: Corner/state_machines/program_close_directly_from_active_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()

    validate_error(
        world.api.close_program(world.program_id, world.admin),
        ERR_PROGRAM_STATE_INVALID,
        409,
    )

    assert_fields(
        world.refresh_program(),
        {"status": "ACTIVE", "posture": "OPEN", "version": 2},
    )


def test_a_second_activation_is_a_conflict_rather_than_a_no_op(world):
    """Replaying a completed transition must not bump the version again.

    "Activation moves the program `DRAFT → ACTIVE` and is refused unless the program
    is currently `DRAFT`, its `incentive_budget_usd` is strictly greater than zero, and
    its `required_question_keys` contains at least the three topics
    `EVALUATION_CRITERIA`, `COMPETITOR_POSITIONING` and `PRICING_PERCEPTION`."

    Design: Corner/state_machines/program_activate_twice_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()

    validate_error(
        world.api.activate_program(world.program_id, world.admin),
        ERR_PROGRAM_STATE_INVALID,
        409,
    )

    assert_field(world.refresh_program(), "version", 2)


def test_sealing_under_a_draft_program_names_the_program_not_the_frame(world):
    """The frame is in the right from-state; only the cross-entity condition fails.

    "Sealing moves the frame `DRAFT → SEALED` and requires that the frame is currently
    `DRAFT`, that the owning program's `status` is `ACTIVE`, and that the three quotas
    sum to at least 1."

    Design: Corner/state_machines/frame_seal_while_program_still_draft_rejected
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.create_program(name="Q3 Win-Loss", fiscal_quarter="2026-Q3")
    world.create_analyst()
    frame = world.create_frame(label="Wave 1")

    validate_error(
        world.api.seal_frame(frame["id"], world.analyst_headers),
        ERR_PROGRAM_STATE_INVALID,
        409,
    )

    stored = world.get_frame(frame["id"])
    assert_field(stored, "status", "DRAFT")
    assert_frame_slots(stored, open_lost=0)


def test_sealing_materialises_every_quota_into_its_open_slot(world):
    """Two, two and one appear in one shot and coverage starts from zero.

    "Sealing initialises `open_won_slots`, `open_lost_slots` and
    `open_no_decision_slots` to `quota_won`, `quota_lost` and `quota_no_decision`
    respectively, sets `coverage_ratio` to 0.0000, and increments the frame's
    `version`."

    Design: Corner/state_machines/frame_seal_initialises_open_slots_and_coverage_ratio
    """
    _program_with_one_registered_analyst(world)
    frame = world.create_frame(label="Wave 1")

    body = validate_success(
        world.api.seal_frame(frame["id"], world.analyst_headers), 200
    )
    sealed = body

    assert_field(sealed, "status", "SEALED")
    assert_frame_slots(sealed, open_won=2, open_lost=2, open_no_decision=1, coverage=0.0000)
    assert_field(sealed, "version", 2)


def test_begin_closing_closes_a_sealed_and_a_draft_frame_at_once(world):
    """The CLOSING floor also tightens posture even though nothing was spent.

    "The `ACTIVE → CLOSING` step requires that no interview belonging to any of the
    program's deals is still `SCHEDULED`; it recomputes `posture` under the `CLOSING`
    floor, which forces the result to at least `RESTRICTED`, closes every sampling
    frame of the program whose `status` is `DRAFT`, `SEALED` or `SUSPENDED`, and
    increments `version`."

    Design: Corner/state_machines/begin_closing_cascades_every_open_frame_to_closed
    """
    _program_with_one_registered_analyst(world)
    sealed = world.create_frame(label="Wave 1")
    world.seal_frame(sealed["id"])
    draft = world.create_frame(
        label="Wave 2",
        window_start="2026-07-01T00:00:00.000Z",
        window_end="2026-10-01T00:00:00.000Z",
        quota_won=1,
        quota_lost=1,
        quota_no_decision=0,
        selection_basis="VALUE_WEIGHTED",
    )

    body = validate_success(
        world.api.begin_closing_program(world.program_id, world.admin), 200
    )
    program = body

    assert_fields(program, {"status": "CLOSING", "posture": "RESTRICTED"})
    assert_field(world.get_frame(sealed["id"]), "status", "CLOSED")
    assert_field(world.get_frame(draft["id"]), "status", "CLOSED")
    assert_ratio(world.get_frame(sealed["id"])["coverage_ratio"], 0.0000, "coverage_ratio")


def test_raising_the_budget_lifts_the_freeze_and_resumes_the_frame(world):
    """The return leg of the suspension loop runs inside the budget replacement.

    "On success the budget is replaced, `posture` is recomputed, and if that
    recomputation moves the posture out of `FROZEN`, every sampling frame of the
    program whose `status` is `SUSPENDED` transitions back to `SEALED`; `version`
    increments."

    Design: Corner/state_machines/suspended_frame_returns_to_sealed_when_budget_raise_lifts_frozen_posture
    """
    _drawn_lost_deal(world, incentive_budget_usd=300.00)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=3)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:20:00.000Z"
    )
    assert_field(world.refresh_program(), "posture", "FROZEN")
    assert_field(world.get_frame(), "status", "SUSPENDED")

    body = validate_success(
        world.api.replace_incentive_budget(
            world.program_id,
            f.incentive_budget_payload(1000.00, world.refresh_program()["version"]),
            world.admin,
        ),
        200,
    )
    program = body

    assert_money(program["incentive_budget_usd"], 1000.00, "incentive_budget_usd")
    assert_ledger(program, 0.00, 312.50, "OPEN")
    frame = world.get_frame()
    assert_field(frame, "status", "SEALED")
    assert_frame_slots(frame, selected_lost=1, open_lost=1)


def test_an_updated_guide_never_reaches_an_already_scheduled_interview(world):
    """The program moves to a four-topic guide while the booking keeps its three.

    "Crucially, there is **no** back-propagation: interviews already in `SCHEDULED`
    keep the `guide_version_pinned` and `required_question_keys_pinned` values they
    captured at scheduling time, and their completion coverage is judged against that
    pinned array rather than the program's current one."

    Design: Corner/state_machines/interview_guide_update_does_not_backpropagate_to_scheduled_interview
    """
    _drawn_lost_deal(world)
    world.schedule_interview()

    body = validate_success(
        world.api.replace_interview_guide(
            world.program_id,
            f.interview_guide_payload(
                [
                    "EVALUATION_CRITERIA",
                    "COMPETITOR_POSITIONING",
                    "PRICING_PERCEPTION",
                    "LOSS_REASON",
                ]
            ),
            world.admin,
        ),
        200,
    )
    program = body

    assert_field(program, "guide_version", 2)
    assert len(program["required_question_keys"]) == 4, program["required_question_keys"]
    interview = world.get_interview()
    assert_field(interview, "guide_version_pinned", 1)
    pinned = interview["required_question_keys_pinned"]
    assert len(pinned) == 3, f"the pinned guide must stay at three topics, got {pinned}"
    assert "LOSS_REASON" not in pinned, f"the new topic leaked into {pinned}"
    assert_fields(interview, {"status": "SCHEDULED", "coverage_complete": False})


# ---------------------------------------------------------------------------
# Interview, attribution and battlecard
# ---------------------------------------------------------------------------


def test_completing_an_interview_twice_does_not_pay_twice(world):
    """The replayed completion conflicts and the paid total stays at one payment.

    "The second link, caused by that incentive-status change, decreases the program's
    `incentive_committed_usd` by the provisional amount, increases its
    `incentive_paid_usd` by the final amount, and increments the program's `version`."

    Design: Corner/state_machines/interview_complete_on_already_completed_interview_rejected
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=3)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )

    validate_error(
        world.api.complete_interview(
            world.interview["id"],
            f.complete_interview_payload(
                "2026-08-10T14:00:00.000Z", "2026-08-10T15:00:00.000Z"
            ),
            world.analyst_headers,
        ),
        ERR_INTERVIEW_STATE_INVALID,
        409,
    )

    interview = world.get_interview()
    assert_fields(interview, {"status": "COMPLETED", "incentive_status": "PAID"})
    assert_money(interview["incentive_final_usd"], 250.00, "incentive_final_usd")
    assert_ledger(world.refresh_program(), 0.00, 250.00)
    assert_analyst_workload(world.get_analyst(), 0, 0)


def test_ratification_moves_both_ancestor_rollups_at_once(world):
    """The cited reason and the deal's competitor each gain exactly one.

    "On success `ratified_by_analyst_id` records the ratifier, the deal's
    `attribution_status` becomes `RATIFIED`, and the deal's research dimension advances
    `INTERVIEWED → SYNTHESIZED`. The primary reason's `ratified_attribution_count`
    increases by one, and so does the secondary reason's when one is present. When the
    deal's `outcome` is `LOST` or `NO_DECISION` and the deal names a
    `primary_competitor_id`, that competitor's `ratified_loss_count` increases by one."

    Design: Corner/state_machines/ratify_syncs_reason_and_competitor_rollup_counters
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_two_analysts()
    reason = world.create_reason("PRICE", "Price")
    world.create_deal(primary_competitor_id=world.competitor["id"])
    world.consented_contact(incentive_eligibility="ELIGIBLE")
    world.create_frame()
    world.seal_frame()
    world.draw("LOST", requested_count=1)
    world.schedule_interview()
    world.cover_guide(recorded_at="2026-08-10T14:10:00.000Z", rating=3)
    world.set_clock("2026-08-10T15:30:00.000Z")
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z", actual_end_at="2026-08-10T15:00:00.000Z"
    )
    attribution = world.create_attribution(reason["id"], weight_primary=1.00)

    body = validate_success(
        world.api.ratify_loss_attribution(
            attribution["id"], world.analyst2_headers
        ),
        200,
    )
    ratified = body

    assert_field(ratified, "status", "RATIFIED")
    assert_field(ratified, "ratified_by_analyst_id", world.analyst2["id"])
    assert_money(ratified["confidence_score"], 0.60, "confidence_score")
    assert_field(world.get_reason(reason["id"]), "ratified_attribution_count", 1)
    assert_field(world.get_competitor(), "ratified_loss_count", 1)
    assert_deal_dimensions(
        world.get_deal(), research_status="SYNTHESIZED", attribution_status="RATIFIED"
    )


def test_one_rejected_claim_sends_the_whole_card_back_to_authoring(world):
    """The card never reaches APPROVED, and the rejected claim leaves the risk set.

    "When the card is in `LEGAL_REVIEW` and any claim on it is rejected, the card
    instead auto-transitions `LEGAL_REVIEW → DRAFT`, recomputing both indices and
    incrementing `version`; no publication side effect fires and the card simply
    returns to authoring, which closes the `DRAFT → LEGAL_REVIEW → DRAFT` revision
    cycle."

    Design: Corner/state_machines/battlecard_returns_to_draft_when_one_claim_is_rejected_in_legal_review
    """
    _card_in_legal_review_with_one_claim_decided(world)

    body = validate_success(
        world.api.legal_decision(
            world.battlecard["id"],
            world.feature_claim["id"],
            f.legal_decision_payload("REJECT"),
            world.legal,
        ),
        200,
    )

    assert_field(body, "legal_status", "REJECTED")
    card = world.get_battlecard()
    assert_field(card, "status", "DRAFT")
    assert_claim_counters(card, approved=1, rejected=1, conditional=0)
    assert_risk_indices(card, 1.00, 1.00)
    assert_null(card["published_at"], "published_at")


def test_clearing_the_last_pending_claim_approves_the_card_with_a_discount(world):
    """Two cleared claims average 1.50, and the mid tier scales fully to 1.35.

    "Stage three selects a legal-review discount keyed on `risk_index_pre` itself,
    never on the running final value: a `risk_index_pre` of at least 2.50 gives a
    discount of twenty-five hundredths, otherwise at least 1.50 gives ten hundredths,
    otherwise none."

    Design: Corner/state_machines/battlecard_auto_approves_when_last_pending_claim_is_cleared
    """
    _card_in_legal_review_with_one_claim_decided(world)

    body = validate_success(
        world.api.legal_decision(
            world.battlecard["id"],
            world.feature_claim["id"],
            f.legal_decision_payload("APPROVE"),
            world.legal,
        ),
        200,
    )
    claim = body

    assert_field(claim, "legal_status", "APPROVED")
    assert claim["decided_at"] == "2026-08-01T00:00:00.000Z", claim["decided_at"]
    card = world.get_battlecard()
    assert_field(card, "status", "APPROVED")
    assert_claim_counters(card, approved=2, rejected=0, conditional=0)
    assert_risk_indices(card, 1.50, 1.35)


def test_a_card_withdrawn_by_the_program_close_can_never_be_reopened(world):
    """WITHDRAWN has no outgoing edge, not even the reopen one.

    "This includes terminal-state lockdown: a `CLOSED` program, a `DECLINED` or
    `SYNTHESIZED` deal, a `COMPLETED` or `CANCELLED` interview, a `WITHDRAWN` card, a
    `REJECTED` claim, a `PROMOTED` or `DECLINED` gap, and a `TRAINED` or `EXPIRED`
    assignment all refuse every further transition."

    Design: Corner/state_machines/battlecard_withdrawn_by_program_close_cannot_be_reopened
    """
    world.set_clock("2026-08-01T00:00:00.000Z")
    world.active_program()
    world.create_competitor()
    world.create_analyst()
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.begin_closing()
    world.close_program()

    validate_error(
        world.api.reopen_battlecard(
            world.battlecard["id"],
            world.analyst_headers,
            f.reopen_payload(reopen_reason="Need to revive the card"),
        ),
        ERR_BATTLECARD_STATE_INVALID,
        409,
    )

    card = world.get_battlecard()
    assert_field(card, "status", "WITHDRAWN")
    assert_field(card, "reopen_count", 0)
    assert_fields(world.refresh_program(), {"status": "CLOSED", "posture": "FROZEN"})


def test_reopening_expires_the_untrained_rep_and_spares_the_trained_one(world):
    """The cascade is conditional on child state, so adoption holds at half.

    "When a published card is reopened, or when it is withdrawn by the claim rejection
    cascade, every assignment on it in `ASSIGNED` or `FAILED` transitions to
    `EXPIRED`, `adoption_rate` is recomputed and each assignment's `version`
    increments."

    Design: Corner/state_machines/assigned_enablement_expires_when_battlecard_is_reopened_while_trained_survives
    """
    _drawn_lost_deal(world)
    world.schedule_interview()
    positioning = world.record_response(
        question_key="COMPETITOR_POSITIONING",
        verbatim_text="Northwind demoed deeper analytics",
        recorded_at="2026-08-01T10:05:00.000Z",
        rating=4,
        competitor_name_verbatim="Northwind",
    )
    world.record_response(
        question_key="EVALUATION_CRITERIA",
        verbatim_text="Integration depth ranked first",
        recorded_at="2026-08-01T10:10:00.000Z",
    )
    world.record_response(
        question_key="PRICING_PERCEPTION",
        verbatim_text="List price felt high for the tier",
        recorded_at="2026-08-01T10:15:00.000Z",
    )
    world.complete_interview(
        actual_start_at="2026-08-10T14:00:00.000Z",
        actual_end_at="2026-08-10T15:00:00.000Z",
    )
    world.create_battlecard(title="Northwind Battlecard", version_label="v1")
    world.add_claim(
        [positioning["id"]],
        claim_text="Two enterprise buyers referenced our security depth",
        claim_type="REFERENCE",
    )
    world.submit_legal()
    world.decide_claim("APPROVE")
    world.publish_battlecard()
    trained = world.assign(
        sales_rep_user_ref="rep-alpha", due_at="2026-08-20T00:00:00.000Z"
    )
    untrained = world.assign(
        sales_rep_user_ref="rep-beta", due_at="2026-08-20T00:00:00.000Z"
    )
    world.complete_assignment(
        quiz_score=80, assignment_id=trained["id"], sales_rep_user_ref="rep-alpha"
    )

    body = validate_success(
        world.api.reopen_battlecard(
            world.battlecard["id"],
            world.analyst_headers,
            f.reopen_payload(reopen_reason="Refresh pricing section"),
        ),
        200,
    )
    card = body

    assert_fields(
        card,
        {"status": "DRAFT", "reopen_count": 1, "assigned_count": 2, "trained_count": 1},
    )
    assert_ratio(card["adoption_rate"], 0.5000, "adoption_rate")
    expired = world.get_assignment(untrained["id"])
    assert_field(expired, "status", "EXPIRED")
    assert_null(expired["completed_at"], "completed_at")
    survivor = world.get_assignment(trained["id"])
    assert_field(survivor, "status", "TRAINED")
    assert_field(survivor, "quiz_score", 80)
    assert_field(world.get_competitor(), "published_battlecard_count", 0)
