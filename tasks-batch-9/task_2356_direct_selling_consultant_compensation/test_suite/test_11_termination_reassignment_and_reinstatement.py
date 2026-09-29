"""Rewriting the genealogy: what a termination moves, what it recomputes, what a reinstatement gives
back, and the preconditions guarding the way home."""

from test_helpers import (
    assert_consultant,
    assert_instant,
    constants as k,
    factories as f,
    fixtures as fx,
    TEST_USERS,
    validate_error,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
COMPLIANCE = TEST_USERS["compliance_officer_headers"]


def _open_period_three_generations(api):
    """A -> B -> C with 600, 100 and 2400 paid points in a period that was never locked."""
    state = fx.setup_three_generation_volume(api, adjust_a_to=None)
    row = fx.qualification_of(api, state["a"]["id"], state["period"]["id"])
    assert row["group_volume_points"] == 3100, "600 plus 100 plus 2,400 while the period is live"
    assert row["active_leg_count"] == 1, "B's 2,500-point leg clears active_leg_min_points 300"
    assert fx.read_consultant(api, state["c"]["id"])["genealogy_depth"] == 2, "C starts two deep"
    return state


def _plan_count(api, plan_id):
    return validate_success(api.get_compensation_plan(plan_id, ADMIN))["consultant_count"]


def _live_consultants(api, plan_id):
    rows = validate_success(api.list_consultants(ADMIN, params={"compensation_plan_id": plan_id}))
    return [row for row in rows if row["status"] != "TERMINATED"]


def test_terminating_the_root_reassigns_its_child_upward_and_redraws_the_paths_below(api):
    """B is lifted to the top with the edge it came from recorded, and C — untouched by the call —
    is nonetheless moved one level up because her ancestor moved.

    PRD: "Every direct downline consultant whose status is not `TERMINATED` is then reassigned
    upward: their `sponsor_consultant_id` is set to the terminated consultant's own
    `sponsor_consultant_id`, which is null when the terminated consultant was a root; their
    `reassigned_from_sponsor_consultant_id` is set to the terminated consultant's identifier,
    retained so that a later reinstatement can find the edge again; and their `reassignment_count`
    is incremented by 1."

    Design: Difficulty/transitive_cascade/root_termination_cascades_sponsor_rewrite_to_upline_paths_to_group_volume
    """
    state = _open_period_three_generations(api)

    terminated = fx.terminate_consultant(api, state["a"], termination_reason="VOLUNTARY")
    assert_consultant(terminated)
    assert terminated["status"] == "TERMINATED", "the root leaves the organisation"
    assert_instant(terminated["terminated_at"], k.INITIAL_CLOCK, "terminated_at")
    assert terminated["termination_reason"] == "VOLUNTARY", "the reason is recorded"
    assert terminated["direct_downline_count"] == 0, "the terminated consultant keeps no children"

    middle = fx.read_consultant(api, state["b"]["id"])
    assert middle["sponsor_consultant_id"] is None, "A was a root, so B inherits a null sponsor"
    assert middle["reassigned_from_sponsor_consultant_id"] == state["a"]["id"], (
        "the edge B was moved off is retained for a later reinstatement"
    )
    assert middle["reassignment_count"] == 1, "B was moved exactly once"
    assert middle["genealogy_depth"] == 0, "B is now a root herself"
    assert middle["upline_path"] == [], "a root has an empty upline path"
    assert middle["direct_downline_count"] == 1, "B keeps C"

    leaf = fx.read_consultant(api, state["c"]["id"])
    assert leaf["sponsor_consultant_id"] == state["b"]["id"], "C's own sponsor never changed"
    assert leaf["reassignment_count"] == 0, "C was moved without being reassigned"
    assert leaf["genealogy_depth"] == 1, "C rises with B, transitively"
    assert leaf["upline_path"] == [state["b"]["id"]], "and her path is recomputed one level shorter"


def test_the_rewritten_genealogy_recomputes_the_live_group_volume_it_left_behind(api):
    """The same termination strips B's subtree out of A's live qualification row, drops A's active
    leg to zero and decrements the plan's headcount, while A's own volume history survives.

    PRD: "For every qualification period whose status is `OPEN` or `REOPENED`, the qualification
    rows of every ancestor of the moved subtree have `group_volume_points` and `active_leg_count`
    recomputed."

    Design: Difficulty/transitive_cascade/root_termination_cascades_sponsor_rewrite_to_upline_paths_to_group_volume
    """
    state = _open_period_three_generations(api)
    plan_id = state["env"]["plan"]["id"]
    assert _plan_count(api, plan_id) == 3, "three consultants are enrolled on the plan"

    fx.terminate_consultant(api, state["a"], termination_reason="VOLUNTARY")

    top = fx.qualification_of(api, state["a"]["id"], state["period"]["id"])
    assert top["group_volume_points"] == 600, "only A's own net personal volume remains beneath her"
    assert top["active_leg_count"] == 0, "the leg that carried 2,500 points is no longer hers"
    assert top["net_personal_volume_points"] == 600, (
        "termination never deletes volume history: the row survives with its personal volume"
    )

    middle = fx.qualification_of(api, state["b"]["id"], state["period"]["id"])
    assert middle["group_volume_points"] == 2500, "B's own 100 plus C's 2,400"
    assert middle["active_leg_count"] == 1, "C's subtree is still B's active leg"

    assert _plan_count(api, plan_id) == 2, "the plan's headcount falls by one"
    assert len(_live_consultants(api, plan_id)) == 2, "and the surviving rows agree with it"


def test_the_plan_headcount_is_a_reconciled_count_of_the_rows_that_are_not_terminated(api):
    """The counter is not a write-once tally: it reads 3, then 2, then 3 again, and at every
    checkpoint it equals the number of consultants of the plan whose status is not TERMINATED.

    PRD: "The plan tracks `consultant_count`, the number of consultants enrolled on it whose status
    is not `TERMINATED`, which starts at 0 and moves as consultants are minted, terminated and
    reinstated."

    Design: Difficulty/compensating_invariant/plan_consultant_count_reconciles_across_termination_and_reinstatement
    """
    env = fx.setup_environment(api)
    assert _plan_count(api, env["plan"]["id"]) == 0, "a fresh plan carries nobody"
    people = fx.setup_genealogy_abc(api, env)
    plan_id = env["plan"]["id"]

    assert _plan_count(api, plan_id) == 3, "each approval increments the counter"
    assert len(_live_consultants(api, plan_id)) == 3, "the counter matches the rows"

    terminated = fx.terminate_consultant(api, people["c"], termination_reason="VOLUNTARY")
    assert terminated["status"] == "TERMINATED", "the leaf leaves the organisation"
    assert_instant(terminated["terminated_at"], k.INITIAL_CLOCK, "terminated_at")
    assert _plan_count(api, plan_id) == 2, "the counter falls with the termination"
    assert len(_live_consultants(api, plan_id)) == 2, "and still matches the rows"
    retained = validate_success(
        api.list_consultants(ADMIN, params={"compensation_plan_id": plan_id, "status": "TERMINATED"})
    )
    assert [row["id"] for row in retained] == [people["c"]["id"]], (
        "the row is retained and listable, only excluded from the count"
    )

    reinstated = fx.reinstate_consultant(api, people["c"], note="returned within the window")
    assert reinstated["status"] == "ACTIVE", "TERMINATED is exitable inside the window"
    assert reinstated["reinstatement_count"] == 1, "the return is counted"
    assert _plan_count(api, plan_id) == 3, "the counter rises again to three"
    assert len(_live_consultants(api, plan_id)) == 3, "reconciling with the rows a third time"
    assert validate_success(
        api.list_consultants(ADMIN, params={"compensation_plan_id": plan_id, "status": "TERMINATED"})
    ) == [], "nobody is terminated on this plan any more"


def test_a_reinstated_consultant_comes_back_without_her_downline_or_her_rank(api):
    """Two terminations take the counter down to one; reinstating the middle consultant brings it
    back to two but returns neither the organisation she lost nor the rung she held.

    PRD: "The downline that was reassigned away at termination is **not** returned — reassignment is
    permanent, and the reinstated consultant rebuilds their organisation from the edge up."

    PRD: "`rank_code` and `rank_order` are reset to the `rank_order` 1 rung with `rank_source` set
    to `REINSTATEMENT`, and `consecutive_qualified_count` and `grace_periods_used` are reset to 0."

    Design: Difficulty/compensating_invariant/plan_consultant_count_reconciles_across_termination_and_reinstatement
    """
    env = fx.setup_environment(api)
    people = fx.setup_genealogy_abc(api, env)
    plan_id = env["plan"]["id"]
    promoted = fx.adjust_rank(api, people["b"], "DIRECTOR", adjustment_reason="legacy plan rank")
    assert promoted["rank_code"] == "DIRECTOR", "B holds an administratively granted rung"

    fx.terminate_consultant(api, people["a"], termination_reason="VOLUNTARY")
    assert _plan_count(api, plan_id) == 2, "the first termination takes the count to two"
    fx.terminate_consultant(api, people["b"], termination_reason="ADMINISTRATIVE")
    assert _plan_count(api, plan_id) == 1, "the second takes it to one"

    orphan = fx.read_consultant(api, people["c"]["id"])
    assert orphan["sponsor_consultant_id"] is None, "C inherits B's own null sponsor"
    assert orphan["reassigned_from_sponsor_consultant_id"] == people["b"]["id"], (
        "C was moved off B, which is the edge a reinstatement would look for"
    )
    assert orphan["reassignment_count"] == 1, "only B's termination moved C"

    reinstated = fx.reinstate_consultant(api, people["b"], note="appeal upheld")
    assert reinstated["status"] == "ACTIVE", "B is back inside the reinstatement window"
    assert reinstated["reinstatement_count"] == 1, "the return is counted once"
    assert_instant(reinstated["reinstated_at"], k.INITIAL_CLOCK, "reinstated_at")
    assert_instant(reinstated["terminated_at"], k.INITIAL_CLOCK, "terminated_at is kept for audit")
    assert reinstated["sponsor_consultant_id"] is None, (
        "the edge B was moved off belongs to a terminated consultant with no live ancestor"
    )
    assert reinstated["direct_downline_count"] == 0, "C is not handed back"
    assert reinstated["rank_code"] == "CONSULTANT", "the rank resets to the first rung"
    assert reinstated["rank_order"] == 1, "which is rank_order 1"
    assert reinstated["rank_source"] == "REINSTATEMENT", "and the source records why"
    assert reinstated["consecutive_qualified_count"] == 0, "the tenure counters restart"
    assert reinstated["grace_periods_used"] == 0, "including the grace allowance"
    assert reinstated["active_sanction_level"] is None, "no sanction survives the return"

    assert _plan_count(api, plan_id) == 2, "the counter rises to two, reconciling with the rows"
    assert len(_live_consultants(api, plan_id)) == 2, "B and C are the two live consultants"
    assert fx.read_consultant(api, people["c"]["id"])["sponsor_consultant_id"] is None, (
        "C stays where the reassignment put her"
    )


def test_reinstatement_and_rank_adjustment_each_refuse_what_their_own_guards_forbid(api):
    """An active consultant cannot be reinstated, an unknown rung cannot be granted, a terminated
    consultant cannot be re-ranked, an open case blocks the way back, and the window can run out.

    PRD: "**Reinstatement** is reserved to a `ComplianceOfficer`, takes an optional
    `reinstatement_note`, and is guarded by four checks in this order: the consultant's status must
    be `TERMINATED`, or `ERR_CONSULTANT_NOT_TERMINATED`; the logical clock must be at or before
    `terminated_at` plus the plan's `reinstatement_window_days`, or
    `ERR_REINSTATEMENT_WINDOW_EXPIRED`, after which the consultant must re-enroll from scratch;
    `clawback_balance_cents` must be 0, or `ERR_CLAWBACK_OUTSTANDING`, since outstanding receivables
    must be settled first; and no compliance case of the consultant may be in `OPEN`,
    `UNDER_REVIEW` or `APPEALED`, or `ERR_OPEN_CASE_BLOCKS_REINSTATEMENT`."

    PRD: "Two checks guard it: the consultant's status must be neither `SUSPENDED` nor
    `TERMINATED`, or `ERR_CONSULTANT_NOT_ADJUSTABLE`, since ranks are not adjusted under suspension
    or after termination; and the submitted `rank_code` must exist in the consultant's plan
    `rank_ladder`, since ranks are plan-scoped, or `ERR_RANK_CODE_UNKNOWN`."

    Design: Corner/state_machines/reinstatement_and_rank_adjustment_preconditions
    """
    env = fx.setup_environment(api)
    ann = fx.enroll_root(api, env, "ann@example.com", "Ann Root")
    bob = fx.enroll_consultant(
        api, env, "bob@example.com", "Bob Mid", sponsor_consultant_id=ann["id"]
    )
    case = fx.open_case(api, bob, claim_type="PRODUCT_CLAIM", evidence_reference="EV-B")
    assert case["status"] == "OPEN", "the case against B is open throughout"

    validate_error(
        api.reinstate_consultant(ann["id"], f.reinstatement_payload("premature"), COMPLIANCE),
        "ERR_CONSULTANT_NOT_TERMINATED",
        409,
    )
    validate_error(
        api.adjust_consultant_rank(
            ann["id"], f.rank_adjustment_payload("GRAND_POOBAH", "typo"), ADMIN
        ),
        "ERR_RANK_CODE_UNKNOWN",
        422,
    )

    adjusted = fx.adjust_rank(
        api, ann, "DIRECTOR", adjustment_reason="Acquisition of a sales team"
    )
    assert adjusted["rank_code"] == "DIRECTOR", "a known rung is granted administratively"
    assert adjusted["rank_order"] == 3, "DIRECTOR is the third rung of the default ladder"
    assert adjusted["rank_source"] == "ADMIN_ADJUSTED", "the grant records its own source"
    assert adjusted["status"] == "ACTIVE", "the adjustment changes no other dimension"

    terminated_bob = fx.terminate_consultant(api, bob, termination_reason="DISCIPLINARY")
    assert terminated_bob["status"] == "TERMINATED", "B leaves with her case still open"
    assert terminated_bob["open_case_count"] == 1, "termination closes nobody's compliance case"

    validate_error(
        api.reinstate_consultant(bob["id"], f.reinstatement_payload("appeal upheld"), COMPLIANCE),
        "ERR_OPEN_CASE_BLOCKS_REINSTATEMENT",
        409,
    )
    validate_error(
        api.adjust_consultant_rank(bob["id"], f.rank_adjustment_payload("DIRECTOR"), ADMIN),
        "ERR_CONSULTANT_NOT_ADJUSTABLE",
        409,
    )

    fx.terminate_consultant(api, ann, termination_reason="VOLUNTARY")
    assert k.PLAN_DEFAULTS["reinstatement_window_days"] == 180, "the window A must return inside"
    fx.set_clock(api, "2027-03-01T00:00:00Z")
    validate_error(
        api.reinstate_consultant(ann["id"], f.reinstatement_payload("too late"), COMPLIANCE),
        "ERR_REINSTATEMENT_WINDOW_EXPIRED",
        422,
    )

    final = fx.read_consultant(api, ann["id"])
    assert final["status"] == "TERMINATED", "A stays out: the window closed on 2027-01-28"
    assert final["reinstatement_count"] == 0, "no reinstatement was ever recorded"
    assert final["rank_code"] == "DIRECTOR", "the granted rung is retained on the terminated row"


def test_a_receivable_left_by_a_reversal_keeps_a_terminated_consultant_out(api):
    """Reversing a paid run turns the disbursement into a debt, which allows the termination and
    then blocks the reinstatement until the balance is cleared.

    PRD: "Two checks guard it, in this order: the consultant must not already be `TERMINATED`, or
    `ERR_CONSULTANT_ALREADY_TERMINATED`; and no commission run in status `APPROVED` may cover a
    period in which this consultant holds an `ACTIVE` statement, or
    `ERR_APPROVED_RUN_BLOCKS_TERMINATION`, because an approved-but-unpaid run must be settled before
    the earner's genealogy is rewritten under it."

    PRD: "`clawback_balance_cents` must be 0, or `ERR_CLAWBACK_OUTSTANDING`, since outstanding
    receivables must be settled first"

    Design: Corner/state_machines/an_outstanding_clawback_balance_blocks_reinstatement
    """
    state = fx.setup_single_earner_paid_run(api)
    assert state["run"]["paid_total_cents"] == 3400, "600 points earned 3,400 cents and were paid"

    reversed_run = fx.reverse_run(api, state["run"], "Volume audit found phantom orders")
    assert reversed_run["status"] == "REVERSED", "the run is unwound"
    assert reversed_run["reversed_total_cents"] == 3400, "the whole disbursement is reversed"
    assert_instant(reversed_run["reversed_at"], k.INITIAL_CLOCK, "reversed_at")

    earner = fx.read_consultant(api, state["a"]["id"])
    assert earner["clawback_balance_cents"] == 3400, "the payment became a receivable"
    assert earner["payout_hold"] is True, "which puts the consultant on hold"
    assert earner["lifetime_commission_paid_cents"] == 0, "and unwinds the lifetime ledger"
    voided = fx.statement_of(api, state["run"]["id"], state["a"]["id"], status="VOIDED")
    assert voided["status"] == "VOIDED", "the statement is voided, never deleted"

    terminated = fx.terminate_consultant(api, state["a"], termination_reason="VOLUNTARY")
    assert terminated["status"] == "TERMINATED", (
        "the termination is admissible because the blocking run is REVERSED rather than APPROVED"
    )

    validate_error(
        api.reinstate_consultant(
            state["a"]["id"], f.reinstatement_payload("wants back in"), COMPLIANCE
        ),
        "ERR_CLAWBACK_OUTSTANDING",
        422,
    )
    final = fx.read_consultant(api, state["a"]["id"])
    assert final["status"] == "TERMINATED", "the debt keeps her out"
    assert final["reinstatement_count"] == 0, "and no return was recorded"
    assert final["clawback_balance_cents"] == 3400, "the balance is untouched by the refusal"
