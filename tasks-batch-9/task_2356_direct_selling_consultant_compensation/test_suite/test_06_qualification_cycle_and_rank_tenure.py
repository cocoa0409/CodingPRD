"""The qualification cycle: half-open period intervals, the lock and close pipeline, and the
rank tenure the close settles."""

from test_helpers import (
    assert_bucket_counts_and_shares,
    assert_commission_run,
    assert_commission_statement,
    assert_income_disclosure_statement,
    assert_instant,
    assert_period_qualification,
    assert_qualification_period,
    constants as k,
    factories as f,
    fixtures as fx,
    TEST_USERS,
    validate_error,
    validate_paginated,
    validate_success,
)

ADMIN = TEST_USERS["platform_admin_headers"]
ANALYST = TEST_USERS["commission_analyst_headers"]
CONTROLLER = TEST_USERS["finance_controller_headers"]

PERIOD_2026_09 = {
    "period_code": "2026-09",
    "period_start": "2026-09-01T00:00:00Z",
    "period_end": "2026-10-01T00:00:00Z",
}
INTERIOR_OVERLAP = {
    "period_code": "2026-08B",
    "period_start": "2026-08-15T00:00:00Z",
    "period_end": "2026-09-15T00:00:00Z",
}
DUPLICATE_CODE_DISJOINT = {
    "period_code": "2026-08",
    "period_start": "2026-10-01T00:00:00Z",
    "period_end": "2026-11-01T00:00:00Z",
}
INVERTED_BOUNDS = {
    "period_code": "2026-11",
    "period_start": "2026-12-01T00:00:00Z",
    "period_end": "2026-11-01T00:00:00Z",
}

# A single-rung ladder whose lowest rung demands one personal volume point, so a
# barren period satisfies no rung at all.
ONE_POINT_LADDER = [
    {
        "rank_code": "CONSULTANT",
        "rank_order": 1,
        "required_pv_points": 1,
        "required_gv_points": 0,
        "required_active_legs": 0,
        "override_levels": 0,
        "override_bp_by_level": [],
    }
]


def _period_response(api, plan_id, spec):
    """Attempt a period creation through the endpoint, returning the raw response."""
    return api.create_qualification_period(
        f.qualification_period_payload(plan_id, **spec), ANALYST
    )


def _period_codes_of_plan(api, plan_id):
    rows, meta = validate_paginated(
        api.list_qualification_periods(ANALYST, params={"compensation_plan_id": plan_id})
    )
    return sorted(row["period_code"] for row in rows), meta["total_count"]


def test_a_period_may_begin_exactly_where_another_ends_and_another_plan_may_twin_it(api):
    """Touching endpoints do not intersect in either direction, and the overlap test is scoped to
    one plan, so a second plan holds the byte-identical August interval.

    PRD: "Periods tile the timeline and adjacency is legal: a new period whose `period_start`
    equals an existing period's `period_end` does not overlap it, because each interval excludes
    its own end instant."

    Design: Difficulty/resource_temporal_overlap/qualification_periods_allow_touching_endpoints_and_reject_interior_overlap
    """
    env = fx.setup_environment(api)
    plan_a = env["plan"]
    plan_b = fx.create_plan(api, plan_code="PLAN-B", name="Consultant Plan B")
    august = env["periods"]["2026-08"]
    assert_qualification_period(august)
    assert august["status"] == "OPEN", "a new period starts OPEN"

    september = validate_success(_period_response(api, plan_a["id"], PERIOD_2026_09), 201)
    assert_instant(september["period_start"], "2026-09-01T00:00:00Z", "period_start")
    assert september["status"] == "OPEN", (
        "a start equal to August's exclusive end does not intersect August"
    )

    july = validate_success(_period_response(api, plan_a["id"], k.PERIOD_2026_07), 201)
    assert_instant(july["period_end"], "2026-08-01T00:00:00Z", "period_end")
    assert july["period_code"] == "2026-07", (
        "an exclusive end equal to August's inclusive start does not intersect August either"
    )

    twin = validate_success(_period_response(api, plan_b["id"], k.PERIOD_2026_08), 201)
    assert twin["compensation_plan_id"] == plan_b["id"], "the twin belongs to the second plan"
    assert twin["period_code"] == august["period_code"], (
        "both code uniqueness and the overlap test are scoped per plan"
    )
    assert_instant(twin["period_start"], august["period_start"], "twin period_start")
    assert_instant(twin["period_end"], august["period_end"], "twin period_end")

    codes_a, count_a = _period_codes_of_plan(api, plan_a["id"])
    assert codes_a == ["2026-07", "2026-08", "2026-09"], "the first plan tiles three months"
    assert count_a == 3, "three periods stand on the first plan"
    codes_b, count_b = _period_codes_of_plan(api, plan_b["id"])
    assert codes_b == ["2026-08"], "the second plan holds only its own August"
    assert count_b == 1, "the twin is the second plan's single period"


def test_interior_overlap_duplicate_code_and_inverted_bounds_are_each_refused(api):
    """An interior straddle, a disjoint interval reusing a taken code and an inverted interval
    are refused with three different errors, and none of them lands a row.

    PRD: "Three rules guard creation, in this order: `period_code` must be unique within the
    plan, or `ERR_DUPLICATE_PERIOD_CODE`; `period_end` must be strictly after `period_start`,
    since empty and inverted periods are meaningless, or `ERR_PERIOD_BOUNDS_INVALID`; and the new
    interval must not intersect any existing period of the same plan, or `ERR_PERIOD_OVERLAP`."

    Design: Difficulty/resource_temporal_overlap/qualification_periods_allow_touching_endpoints_and_reject_interior_overlap
    """
    env = fx.setup_environment(api)
    plan_id = env["plan"]["id"]
    validate_success(_period_response(api, plan_id, PERIOD_2026_09), 201)
    validate_success(_period_response(api, plan_id, k.PERIOD_2026_07), 201)

    validate_error(
        _period_response(api, plan_id, INTERIOR_OVERLAP), "ERR_PERIOD_OVERLAP", 409
    )
    validate_error(
        _period_response(api, plan_id, DUPLICATE_CODE_DISJOINT),
        "ERR_DUPLICATE_PERIOD_CODE",
        409,
    )
    validate_error(
        _period_response(api, plan_id, INVERTED_BOUNDS), "ERR_PERIOD_BOUNDS_INVALID", 422
    )

    codes, count = _period_codes_of_plan(api, plan_id)
    assert codes == ["2026-07", "2026-08", "2026-09"], (
        "only the three admitted periods stand; no refused attempt was persisted"
    )
    assert count == 3, "three rows after three rejections"


def test_out_of_order_period_and_run_triggers_are_refused_from_every_wrong_state(api):
    """Close, reopen, run creation, approval, payment, reversal, disclosure drafting and
    recalculation are each attempted from the one state that forbids them.

    PRD: "A run's `status` moves across `DRAFT`, `CALCULATED`, `APPROVED`, `PAID` and
    `REVERSED`, starting at `DRAFT`, and its lifecycle state is checked before anything else that
    operation cares about: calculating requires `DRAFT` or fails with `ERR_RUN_NOT_DRAFT`, taking
    an approval decision requires `CALCULATED` or fails with `ERR_RUN_NOT_CALCULATED`, paying
    requires `APPROVED` or fails with `ERR_RUN_NOT_APPROVED`, and reversing requires `PAID` or
    fails with `ERR_RUN_NOT_PAID`."

    Design: Corner/state_machines/illegal_lifecycle_moves_on_qualification_periods_and_commission_runs
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    period = env["periods"]["2026-08"]
    fx.place_and_pay_order(api, env, alice, [("SERUM", 30)], order_type="BUSINESS_SUPPLY")

    validate_error(
        api.close_qualification_period(period["id"], None, ANALYST), "ERR_PERIOD_NOT_LOCKED", 409
    )
    validate_error(
        api.reopen_qualification_period(period["id"], f.reopen_payload("too early"), ADMIN),
        "ERR_PERIOD_NOT_CLOSED",
        409,
    )
    open_version = fx.read_period(api, period["id"])["version"]
    validate_error(
        api.create_commission_run(
            f.commission_run_payload(period["id"], open_version), ANALYST
        ),
        "ERR_PERIOD_NOT_CLOSED",
        409,
    )

    locked = fx.lock_period(api, period)
    assert locked["status"] == "LOCKED", "the first lock is legal"
    validate_error(
        api.lock_qualification_period(period["id"], None, ANALYST), "ERR_PERIOD_NOT_OPEN", 409
    )

    closed = fx.close_period(api, locked)
    assert closed["status"] == "CLOSED", "the close is legal from LOCKED"

    run = fx.create_run(api, closed)
    assert run["status"] == "DRAFT", "a new run starts DRAFT"
    assert run["period_code"] == "2026-08", "the run denormalises the period's code"

    validate_error(
        api.decide_commission_run_approval(
            run["id"], f.approval_decision_payload("APPROVE"), CONTROLLER
        ),
        "ERR_RUN_NOT_CALCULATED",
        409,
    )
    validate_error(
        api.pay_commission_run(run["id"], None, CONTROLLER), "ERR_RUN_NOT_APPROVED", 409
    )
    validate_error(
        api.reverse_commission_run(run["id"], f.reversal_payload("too early"), CONTROLLER),
        "ERR_RUN_NOT_PAID",
        409,
    )

    draft_run_version = validate_success(api.get_commission_run(run["id"], ANALYST))["version"]
    validate_error(
        api.create_income_disclosure_statement(
            f.income_disclosure_payload(run["id"], draft_run_version, "ALL_ENROLLED"), ANALYST
        ),
        "ERR_RUN_NOT_PAID",
        409,
    )

    calculated = fx.calculate_run(api, run)
    assert calculated["status"] == "CALCULATED", "calculation is legal from DRAFT"
    validate_error(
        api.calculate_commission_run(run["id"], None, ANALYST), "ERR_RUN_NOT_DRAFT", 409
    )

    assert fx.read_period(api, period["id"])["status"] == "CLOSED", (
        "the period is still CLOSED after every rejection"
    )
    assert validate_success(api.get_commission_run(run["id"], ANALYST))["status"] == "CALCULATED", (
        "the run is still CALCULATED after every rejection"
    )


def test_lock_close_calculate_approve_pay_and_publish_apply_every_side_effect(api):
    """One root consultant with 600 points is carried through the whole pipeline, and each step's
    declared side effects are read back rather than only its status change.

    PRD: "The lock creates a qualification row for every consultant of the plan whose status is
    not `TERMINATED` and who does not yet have one, so that non-producers are represented with
    zeroes."

    Design: Corner/state_machines/period_lock_close_run_and_disclosure_valid_transitions_with_side_effects
    """
    env = fx.setup_environment(api)
    alice = fx.enroll_root(api, env)
    period = env["periods"]["2026-08"]
    order = fx.place_and_pay_order(
        api, env, alice, [("SERUM", 30)], order_type="BUSINESS_SUPPLY"
    )
    assert order["total_due_cents"] == 69900, "thirty SERUM in TX cost 69,900 cents"

    locked = fx.lock_period(api, period)
    assert locked["status"] == "LOCKED", "the lock froze the period"
    assert locked["qualification_count"] == 1, "exactly one qualification row hangs off the period"
    assert locked["total_net_personal_volume_points"] == 600, "the period's derived volume total"

    row = fx.qualification_of(api, alice["id"], period["id"])
    assert_period_qualification(row)
    assert row["personal_volume_points"] == 600, "thirty units at twenty points each"
    assert row["net_personal_volume_points"] == 600, "nothing was returned"
    assert row["retail_volume_points"] == 0, "a BUSINESS_SUPPLY order is not retail"
    assert row["inventory_volume_points"] == 0, "a BUSINESS_SUPPLY order is not inventory either"
    assert row["group_volume_points"] == 600, "a root with no downline is its own subtree"
    assert row["active_leg_count"] == 0, "there is no downline to count as a leg"
    assert row["sell_through_bp"] == 10000, (
        "with no purchased inventory the ratio is 10,000 by definition rather than a division"
    )
    assert row["qualified_rank_code"] == "CONSULTANT", "600 points clears only the lowest rung"
    assert row["paid_as_rank_code"] == "CONSULTANT", "held and qualified rank agree"
    assert_instant(row["evaluated_at"], k.INITIAL_CLOCK, "evaluated_at")

    closed = fx.close_period(api, locked)
    assert closed["status"] == "CLOSED", "the close settled tenure"
    assert closed["correction_pending"] is False, "the close clears the correction flag"

    run = fx.create_run(api, closed)
    assert_commission_run(run)
    assert run["status"] == "DRAFT", "a new run starts DRAFT"
    assert run["calculation_sequence"] == 0, "nothing has been calculated yet"
    assert run["period_code"] == "2026-08", "the run denormalises the period's code"

    calculated = fx.calculate_run(api, run)
    assert calculated["status"] == "CALCULATED", "the calculation moved the run"
    assert calculated["calculation_sequence"] == 1, "calculation_sequence is incremented by one"
    assert calculated["compression_mode_snapshot"] == "DYNAMIC", "the plan's mode was snapshotted"
    assert calculated["statement_count"] == 1, "one statement per qualification row"
    assert calculated["calculated_by_user_id"] == k.ANALYST_USER_ID, (
        "the calling analyst is recorded for the segregation test"
    )
    assert calculated["gross_total_cents"] == 3400, "the run's gross is its one statement's gross"
    assert calculated["forfeited_to_company_cents"] == 0, "DYNAMIC compression forfeits nothing"
    assert calculated["distributable_pool_cents"] == 3400, "gross plus forfeited"
    assert calculated["withheld_total_cents"] == 0, "nothing is owed, so nothing is withheld"
    assert calculated["net_payable_total_cents"] == 3400, "net equals gross here"

    statement = fx.statement_of(api, run["id"], alice["id"])
    assert_commission_statement(statement)
    assert statement["retail_profit_cents"] == 0, "no retail customer order was placed"
    assert statement["pv_bonus_cents"] == 3400, (
        "500 points at 500 basis points is 2,500 and the next 100 at 900 basis points is 900"
    )
    assert statement["override_total_cents"] == 0, "CONSULTANT pays no override levels"
    assert statement["gross_commission_cents"] == 3400, "the three components sum to 3,400"
    assert statement["withhold_rate_bp"] == 1000, (
        "3,400 is at or below the 20,000-cent threshold, so the low rate applies"
    )
    assert statement["withholding_cents"] == 0, "withholding is capped by the clawback balance of 0"
    assert statement["net_payable_cents"] == 3400, "gross minus withholding"
    assert statement["status"] == "ACTIVE", "the fresh statement is the live generation"
    assert statement["calculation_sequence"] == run["calculation_sequence"], (
        "the statement records the run's calculation_sequence at the moment it was produced, "
        "which PRD §3.5 orders before the run increments it"
    )

    approved = fx.approve_run(api, calculated)
    assert approved["status"] == "APPROVED", "the controller approved the run"
    assert approved["approved_by_user_id"] == k.CONTROLLER_USER_ID, "the approver is recorded"
    assert fx.statement_of(api, run["id"], alice["id"])["payout_status"] == "PAYABLE", (
        "approval marks every ACTIVE statement PAYABLE"
    )

    paid = fx.pay_run(api, approved)
    assert paid["status"] == "PAID", "payment moved the run"
    assert paid["paid_total_cents"] == 3400, "the whole net amount was disbursed"
    assert paid["carry_forward_total_cents"] == 0, "nothing fell below the minimum payout"
    assert_instant(paid["paid_at"], k.INITIAL_CLOCK, "paid_at")

    consultant = fx.read_consultant(api, alice["id"])
    assert consultant["lifetime_commission_paid_cents"] == 3400, (
        "the payment reached the consultant's own ledger"
    )
    assert consultant["carry_forward_cents"] == 0, "nothing was carried forward"
    assert consultant["payout_hold"] is False, "no clawback balance means no hold"

    disclosure = fx.draft_disclosure(api, paid, population_basis="ALL_ENROLLED")
    assert_income_disclosure_statement(disclosure)
    assert disclosure["status"] == "DRAFT", "a new disclosure starts DRAFT"
    assert disclosure["population_count"] == 1, "one non-terminated consultant enrolled in time"
    assert disclosure["total_earnings_cents"] == 3400, "earnings mean gross commission"
    assert disclosure["mean_earnings_cents"] == 3400, "one member's mean is that member"
    assert disclosure["median_earnings_cents"] == 3400, "a single-member list's middle value"
    assert disclosure["p90_earnings_cents"] == 3400, "the nearest-rank ninetieth percentile"
    assert disclosure["top_decile_share_bp"] == 10000, "the one earner is the whole top decile"
    assert disclosure["zero_earner_count"] == 0, "the only member earned"
    assert disclosure["revision_number"] == 0, "no revision round trip has happened"
    assert_bucket_counts_and_shares(disclosure, [0, 1, 0, 0], [0, 10000, 0, 0])

    submitted = fx.submit_disclosure(api, disclosure)
    assert submitted["status"] == "LEGAL_REVIEW", "the analyst submitted the draft"
    assert submitted["submitted_by_user_id"] == k.ANALYST_USER_ID, (
        "the submitter is recorded for the segregation test"
    )

    published = fx.publish_disclosure(api, submitted)
    assert published["status"] == "PUBLISHED", "the reviewer published it"
    assert published["legal_reviewer_user_id"] == k.LEGAL_USER_ID, "the reviewer is recorded"
    assert_instant(published["published_at"], k.INITIAL_CLOCK, "published_at")


def test_one_qualifying_close_is_not_enough_and_the_second_advances_exactly_one_rung(api):
    """A qualifies at SENIOR_CONSULTANT in both months but is paid as CONSULTANT, and her rank
    moves only at the second close, while B never qualifies above her held rank.

    PRD: "Advancement: when a consultant's `qualified_rank_order` for the closing period exceeds
    their held `rank_order`, `consecutive_qualified_count` is incremented, and once it reaches the
    plan's `consecutive_qualifying_periods` the consultant's `rank_code` and `rank_order` advance
    by exactly one rung — never two, however far above their rank they qualified — with
    `rank_source` set to `EARNED` and the counter reset to 0."

    Design: Corner/state_machines/rank_advancement_needs_two_consecutive_qualifying_closed_periods
    """
    tenure = fx.setup_two_period_tenure(api)
    alice, bob = tenure["a"], tenure["b"]
    july, august = tenure["july"], tenure["august"]
    assert k.PLAN_DEFAULTS["consecutive_qualifying_periods"] == 2, "two closes are required"
    assert k.PLAN_DEFAULTS["active_leg_min_points"] == 300, "a leg needs 300 subtree points"

    fx.lock_period(api, july)
    q7 = fx.qualification_of(api, alice["id"], july["id"])
    assert q7["net_personal_volume_points"] == 300, "fifteen SERUM carry 300 points"
    assert q7["group_volume_points"] == 1200, "her own 300 plus 900 from her downline"
    assert q7["active_leg_count"] == 1, "the downline subtree of 900 clears the 300-point bar"
    assert q7["qualified_rank_code"] == "SENIOR_CONSULTANT", (
        "300 personal, 1,200 group and one leg meet the rung exactly, and all three are inclusive"
    )
    assert q7["qualified_rank_order"] == 2, "the matched rung's rank_order"
    assert q7["paid_as_rank_code"] == "CONSULTANT", (
        "paid_as is the lower of the held rank and the qualified rank"
    )

    fx.close_period(api, july)
    after_first = fx.read_consultant(api, alice["id"])
    assert after_first["rank_code"] == "CONSULTANT", "one qualifying close is not enough"
    assert after_first["rank_order"] == 1, "the held rung did not move"
    assert after_first["consecutive_qualified_count"] == 1, "the counter records the first close"
    assert after_first["grace_periods_used"] == 0, "no shortfall occurred"

    locked_august = fx.lock_period(api, august)
    at_lock = fx.read_consultant(api, alice["id"])
    assert at_lock["rank_code"] == "CONSULTANT", (
        "the lock evaluates the row but never advances the consultant"
    )
    assert at_lock["consecutive_qualified_count"] == 1, "the counter moves at close, not at lock"

    fx.close_period(api, locked_august)
    after_second = fx.read_consultant(api, alice["id"])
    assert after_second["rank_code"] == "SENIOR_CONSULTANT", "the second close granted the rung"
    assert after_second["rank_order"] == 2, "exactly one rung above where she started"
    assert after_second["rank_source"] == "EARNED", "the advancement was earned, not adjusted"
    assert after_second["consecutive_qualified_count"] == 0, (
        "the counter resets when the advancement is granted"
    )

    downline = fx.read_consultant(api, bob["id"])
    assert downline["rank_code"] == "CONSULTANT", (
        "900 group points and no active leg never reach the second rung"
    )
    assert downline["consecutive_qualified_count"] == 0, "she never qualified above her held rank"


def test_the_first_shortfall_consumes_grace_and_the_second_demotes_one_rung(api):
    """An administratively granted SENIOR_CONSULTANT who only ever posts 100 points keeps her rank
    through one shortfall and loses a rung at the second close.

    PRD: "Maintenance: when `qualified_rank_order` is below the held `rank_order`,
    `grace_periods_used` is incremented, and once it exceeds the plan's
    `maintenance_grace_periods` the rank is demoted by one rung with `rank_source` set to
    `MAINTENANCE_DEMOTION`."

    Design: Corner/state_machines/maintenance_grace_absorbs_one_shortfall_then_demotion_lands
    """
    tenure = fx.setup_two_period_tenure(
        api, a_pairs=(("SERUM", 5),), b_pairs=(), adjust_a_to="SENIOR_CONSULTANT"
    )
    alice = tenure["a"]
    july, august = tenure["july"], tenure["august"]
    assert k.PLAN_DEFAULTS["maintenance_grace_periods"] == 1, "a single shortfall is forgiven"
    assert alice["rank_code"] == "SENIOR_CONSULTANT", "the rank was granted administratively"
    assert alice["rank_order"] == 2, "she holds the second rung"
    assert alice["rank_source"] == "ADMIN_ADJUSTED", "an override stamps ADMIN_ADJUSTED"

    fx.lock_and_close(api, july)
    q7 = fx.qualification_of(api, alice["id"], july["id"])
    assert q7["net_personal_volume_points"] == 100, "five SERUM carry 100 points"
    assert q7["qualified_rank_code"] == "CONSULTANT", "100 points is one rung below her held rank"
    assert q7["qualified_rank_order"] == 1, "the lowest rung requires nothing"
    assert q7["paid_as_rank_code"] == "CONSULTANT", "she is never paid above what she qualified for"

    after_first = fx.read_consultant(api, alice["id"])
    assert after_first["rank_code"] == "SENIOR_CONSULTANT", "the shortfall is absorbed, not punished"
    assert after_first["rank_order"] == 2, "the held rung survives the first shortfall"
    assert after_first["grace_periods_used"] == 1, "the grace period was consumed"
    assert after_first["consecutive_qualified_count"] == 0, "she qualified below her held rank"

    fx.lock_and_close(api, august)
    q8 = fx.qualification_of(api, alice["id"], august["id"])
    assert q8["net_personal_volume_points"] == 100, "the same volume in the second period"
    assert q8["qualified_rank_code"] == "CONSULTANT", "the second consecutive shortfall"
    assert q8["paid_as_rank_code"] == "CONSULTANT", (
        "the row was evaluated at lock, while she still held the higher rung"
    )

    after_second = fx.read_consultant(api, alice["id"])
    assert after_second["rank_code"] == "CONSULTANT", "the second shortfall exceeds the grace"
    assert after_second["rank_order"] == 1, "the demotion is by exactly one rung"
    assert after_second["rank_source"] == "MAINTENANCE_DEMOTION", (
        "the demotion names itself in rank_source"
    )


def test_a_barren_close_deactivates_and_the_next_close_reactivates(api):
    """On a plan whose lowest rung demands one point, a period of zero volume closes the
    consultant into INACTIVE, and volume already on the books returns her to ACTIVE.

    PRD: "Activity flips are applied in the same pass: a consultant who is `ACTIVE` or
    `PROBATION`, whose row for the closing period has a null `qualified_rank_code`, and whose
    `grace_periods_used` has already reached `maintenance_grace_periods`, transitions
    `ACTIVE → INACTIVE` or `PROBATION → INACTIVE`, with `rank_code` and `rank_order` reset to the
    `rank_order` 1 rung, `rank_source` set to `MAINTENANCE_DEMOTION` and `grace_periods_used`
    reset to 0; conversely a consultant who is `INACTIVE` and whose row for the closing period has
    a non-null `qualified_rank_code` transitions `INACTIVE → ACTIVE`."

    Design: Corner/state_machines/zero_qualifying_volume_deactivates_and_new_volume_reactivates
    """
    fx.set_clock(api, "2026-07-05T00:00:00Z")
    env = fx.setup_environment(
        api,
        plan_overrides={"rank_ladder": ONE_POINT_LADDER, "maintenance_grace_periods": 0},
        plan_code="PLAN-INA",
        periods=(k.PERIOD_2026_07, k.PERIOD_2026_08),
    )
    alice = fx.enroll_root(api, env)
    july, august = env["periods"]["2026-07"], env["periods"]["2026-08"]

    barren = fx.place_and_pay_order(
        api, env, alice, [("CATALOG", 10)], order_type="BUSINESS_SUPPLY", period_code="2026-07"
    )
    assert barren["total_due_cents"] == 2160, "1,000 merchandise plus 165 tax plus 995 shipping"
    assert barren["total_volume_points"] == 0, "the catalogue carries no volume points"

    fx.set_clock(api, "2026-08-05T00:00:00Z")
    productive = fx.place_and_pay_order(
        api, env, alice, [("SERUM", 5)], order_type="BUSINESS_SUPPLY", period_code="2026-08"
    )
    assert productive["total_volume_points"] == 100, "five SERUM carry 100 points"
    assert fx.read_consultant(api, alice["id"])["status"] == "ACTIVE", (
        "both orders were paid while she was still ACTIVE"
    )

    fx.lock_period(api, july)
    q7 = fx.qualification_of(api, alice["id"], july["id"])
    assert q7["net_personal_volume_points"] == 0, "the barren period posted no points"
    assert q7["qualified_rank_code"] is None, "no rung is satisfied when the lowest demands one"
    assert q7["qualified_rank_order"] == 0, "an unmatched ladder leaves the order at zero"
    assert q7["paid_as_rank_code"] is None, "there is nothing to be paid as"
    assert fx.read_consultant(api, alice["id"])["status"] == "ACTIVE", (
        "the lock evaluates the row but never flips activity"
    )

    fx.close_period(api, july)
    after_barren = fx.read_consultant(api, alice["id"])
    assert after_barren["status"] == "INACTIVE", "the barren close deactivated her"
    assert after_barren["rank_code"] == "CONSULTANT", (
        "deactivation resets the rank to the first rung, which is the one she held"
    )
    assert after_barren["rank_order"] == 1, "the only rung of this plan's ladder"
    assert after_barren["grace_periods_used"] == 0, "the flip resets the grace counter"

    fx.lock_period(api, august)
    q8 = fx.qualification_of(api, alice["id"], august["id"])
    assert q8["net_personal_volume_points"] == 100, "the August volume was already on the books"
    assert q8["qualified_rank_code"] == "CONSULTANT", "100 points clears the one-point rung"
    assert fx.read_consultant(api, alice["id"])["status"] == "INACTIVE", (
        "the lock does not reactivate either: both edges belong to the close"
    )

    fx.close_period(api, august)
    after_productive = fx.read_consultant(api, alice["id"])
    assert after_productive["status"] == "ACTIVE", "a non-null qualified rank reactivates her"
    assert after_productive["rank_code"] == "CONSULTANT", "the rank is unchanged by the flip back"
