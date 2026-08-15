"""Bottom-up submissions and reconciliation: window gates, uniqueness,
membership, tolerance boundary, policy variants, and the OCC guard."""
import pytest

from test_helpers import (
    ADMIN,
    ApiErrorId,
    activate_territory,
    add_territory,
    apply_allocation,
    close_submissions,
    compute_run,
    create_allocation,
    create_assignment,
    create_plan,
    create_rep,
    create_submission_payload,
    get_plan,
    get_results_row,
    get_submission,
    get_territory,
    make_sales_rep_headers,
    plan_version,
    setup_dual_reconciliation_policy_plans,
    setup_open_plan,
    setup_open_plan_with_children,
    setup_tolerance_boundary_plan,
    submit,
    validate_error,
    validate_success,
    walk_to_reconciled,
)


def test_submission_in_draft_plan_reports_window_closed_over_amount(api):
    """PRD: "Every request is validated against an eight-tier pipeline, and the
    tiers are evaluated in strict order — a failure in an earlier tier masks
    everything behind it."
    PRD: "creating or withdrawing outside `OPEN` fails with
    `ERR_SUBMISSION_WINDOW_CLOSED`" (tier four) and "Tier eight, evaluated
    last, holds the amount rules: strictly-positive amounts
    (`ERR_AMOUNT_NOT_POSITIVE`, 422), allocation pool agreement
    (`ERR_POOL_MISMATCH`, 409), and ramp-schedule shape
    (`ERR_INVALID_RAMP_SCHEDULE`, 422)."

    A submission against a DRAFT plan with a non-positive amount reports the
    tier-four state error, not the tier-eight amount error.

    Design: Difficulty/priority_pair_validation_conflict/submission_window_closed_beats_amount_not_positive
    """
    plan = create_plan(label="FY27-P1")
    t = add_territory(plan["id"], name="T")
    activate_territory(t["id"])
    rep = create_rep()
    resp = api.create_submission(
        create_submission_payload(plan["id"], t["id"], -5),
        make_sales_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED, 409)


def test_submission_after_close_reports_window_closed_over_amount(api):
    """PRD: "Every request is validated against an eight-tier pipeline, and the
    tiers are evaluated in strict order — a failure in an earlier tier masks
    everything behind it."
    PRD: "creating or withdrawing outside `OPEN` fails with
    `ERR_SUBMISSION_WINDOW_CLOSED`"

    The same dual-failure request against a SUBMISSIONS_CLOSED plan still
    reports the tier-four state error over the tier-eight amount error.

    Design: Difficulty/priority_pair_validation_conflict/submission_window_closed_beats_amount_not_positive
    """
    base = setup_open_plan(label="FY27-P1B")
    rep = create_rep()
    close_submissions(base["plan"]["id"])
    resp = api.create_submission(
        create_submission_payload(base["plan"]["id"], base["t"]["id"], -5),
        make_sales_rep_headers(rep["id"]))
    validate_error(resp, ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED, 409)


def test_duplicate_submission_rejected(api):
    """PRD: "a territory may hold at most one submission in `SUBMITTED` status
    at a time, a second being refused with `ERR_DUPLICATE_SUBMISSION`."

    After withdrawing the first, the same request succeeds.

    Design: Corner/validations/duplicate_submission_rejected
    """
    base = setup_open_plan(label="FY27-DUP")
    plan_id = base["plan"]["id"]
    rep = create_rep()
    create_assignment(plan_id, rep["id"], base["t"]["id"])
    s1 = submit(plan_id, base["t"]["id"], 90000, rep["id"])

    validate_error(api.create_submission(
        create_submission_payload(plan_id, base["t"]["id"], 95000),
        make_sales_rep_headers(rep["id"])),
        ApiErrorId.ERR_DUPLICATE_SUBMISSION, 409)

    withdrawn = validate_success(api.withdraw_submission(
        s1["id"], make_sales_rep_headers(rep["id"])), 200)
    assert withdrawn["status"] == "WITHDRAWN"
    s2 = validate_success(api.create_submission(
        create_submission_payload(plan_id, base["t"]["id"], 95000),
        make_sales_rep_headers(rep["id"])), 201)
    assert s2["status"] == "SUBMITTED"


def test_submission_by_non_member_rejected(api):
    """PRD: "The rep must hold an `ACTIVE` assignment on the proposed territory
    — a submission from a non-member is `ERR_NOT_TERRITORY_MEMBER`"

    Design: Corner/validations/submission_by_non_member_rejected
    """
    base = setup_open_plan(label="FY27-NM")
    rep = create_rep(full_name="R2")
    validate_error(api.create_submission(
        create_submission_payload(base["plan"]["id"], base["t"]["id"], 90000),
        make_sales_rep_headers(rep["id"])),
        ApiErrorId.ERR_NOT_TERRITORY_MEMBER, 409)


def test_submission_non_positive_quota_rejected(api):
    """PRD: "While the plan is `OPEN`, a `SalesRep` may argue the number from
    the field upward by submitting a proposal naming the `plan_year_id`, the
    `territory_id`, a strictly positive `proposed_quota_cents`, and an optional
    free-text `rationale`"
    PRD: "Tier eight, evaluated last, holds the amount rules: strictly-positive
    amounts (`ERR_AMOUNT_NOT_POSITIVE`, 422)"

    proposed_quota_cents == 0 is rejected even when state, membership and
    uniqueness all pass.

    Design: Corner/validations/submission_non_positive_quota_rejected
    """
    base = setup_open_plan(label="FY27-NP")
    plan_id = base["plan"]["id"]
    rep = create_rep()
    create_assignment(plan_id, rep["id"], base["t"]["id"])
    validate_error(api.create_submission(
        create_submission_payload(plan_id, base["t"]["id"], 0),
        make_sales_rep_headers(rep["id"])),
        ApiErrorId.ERR_AMOUNT_NOT_POSITIVE, 422)


def test_submissions_lock_in_on_close_and_withdraw_rejected(api):
    """PRD: "Closing the submission window moves the plan from `OPEN` to
    `SUBMISSIONS_CLOSED` and, as an ops-run checkpoint, every submission still
    in `SUBMITTED` status anywhere in the plan flips to `LOCKED_IN` in the same
    act."
    PRD: "creating or withdrawing outside `OPEN` fails with
    `ERR_SUBMISSION_WINDOW_CLOSED`"

    Design: Corner/state_machines/submissions_lock_in_on_close_and_withdraw_rejected
    """
    base = setup_open_plan(label="FY27-LI")
    plan_id = base["plan"]["id"]
    rep = create_rep()
    create_assignment(plan_id, rep["id"], base["t"]["id"])
    sub = submit(plan_id, base["t"]["id"], 90000, rep["id"])

    close_submissions(plan_id)
    locked_in = get_submission(sub["id"])
    assert locked_in["status"] == "LOCKED_IN"

    validate_error(api.withdraw_submission(
        sub["id"], make_sales_rep_headers(rep["id"])),
        ApiErrorId.ERR_SUBMISSION_WINDOW_CLOSED, 409)


def test_reconciliation_exactly_ten_percent_blends(api):
    """PRD: "otherwise, when the absolute gap times one hundred is less than or
    equal to the top-down figure times ten — a tolerance test performed in
    integer arithmetic exactly as written, with no rounding — the final is the
    midpoint of the two figures rounded half-up to whole cents and the row does
    not escalate"

    bottom_up 1100000 is exactly 10.00% over top_down 1000000:
    |100000| * 100 <= 1000000 * 10, so the row blends to 1050000.

    Design: Difficulty/boundary_precision_check/reconciliation_tolerance_exact_ten_percent
    """
    fx = setup_tolerance_boundary_plan()
    run = validate_success(api.get_reconciliation_run(fx["run"]["id"], ADMIN),
                           200)
    row = get_results_row(run, fx["t1"]["id"])
    assert row["top_down_cents"] == 1000000
    assert row["bottom_up_cents"] == 1100000
    assert row["final_cents"] == 1050000
    assert row["escalated"] is False
    assert row["deviation_pct"] == pytest.approx(10.00, abs=0.005)
    assert get_territory(fx["t1"]["id"])["final_quota_cents"] == 1050000


def test_reconciliation_one_cent_past_tolerance_escalates(api):
    """PRD: "It must never feed the tolerance comparison — a proposal exceeding
    its top-down figure by 10.0001 percent displays a deviation of 10.00 yet
    still escalates."
    PRD: "stores its `results`: one row per `ACTIVE` territory in the plan,
    ordered by territory creation timestamp ascending" and "with
    `bottom_up_cents` and `deviation_pct` null whenever the territory has no
    `LOCKED_IN` submission."

    bottom_up 1100001 escalates to final 1000000 even though the displayed
    deviation also rounds to 10.00; rows are ordered root, T1, T2 and the
    submission-less root row carries null bottom-up fields.

    Design: Difficulty/boundary_precision_check/reconciliation_tolerance_exact_ten_percent
    """
    fx = setup_tolerance_boundary_plan()
    run = validate_success(api.get_reconciliation_run(fx["run"]["id"], ADMIN),
                           200)
    row = get_results_row(run, fx["t2"]["id"])
    assert row["final_cents"] == 1000000
    assert row["escalated"] is True
    assert row["deviation_pct"] == pytest.approx(10.00, abs=0.005), \
        "display rounding must not feed the integer tolerance comparison"
    assert get_territory(fx["t2"]["id"])["final_quota_cents"] == 1000000

    ordered_ids = [r["territory_id"] for r in run["results"]]
    assert ordered_ids == [fx["root"]["id"], fx["t1"]["id"], fx["t2"]["id"]]
    root_row = get_results_row(run, fx["root"]["id"])
    assert root_row["bottom_up_cents"] is None
    assert root_row["deviation_pct"] is None
    assert root_row["final_cents"] == 2000000


def test_recon_zero_topdown_and_missing_submission_branches(api):
    """PRD: "Under the `BLENDED` variant, a territory with no bottom-up
    proposal keeps its top-down final with no escalation; a territory whose
    top-down figure is zero takes the proposal as its final and escalates
    exactly when that proposal is positive"
    PRD: "The `deviation_pct` is display-only: the signed gap between proposal
    and top-down, multiplied by one hundred and divided by the top-down figure,
    rounded half-up to two decimal places, computed only when the top-down
    figure is positive and a proposal exists, and null otherwise."

    Child Z (potential 0, top-down 0) with a 400000 submission lands final
    400000 escalated; child Y with no submission keeps its top-down 1000000.

    Design: Corner/calculations/recon_zero_topdown_and_missing_submission_branches
    """
    fx = setup_open_plan_with_children(potentials=(0, 1000), target=1000000,
                                       label="FY27-ZT",
                                       reconciliation_policy="BLENDED")
    plan_id = fx["plan"]["id"]
    tz, ty = fx["children"]
    alloc = apply_allocation(
        create_allocation(plan_id, fx["root"]["id"], 1000000)["id"], plan_id)
    assert alloc["status"] == "APPLIED"
    rz = create_rep(full_name="RZ")
    create_assignment(plan_id, rz["id"], tz["id"])
    submit(plan_id, tz["id"], 400000, rz["id"])
    run = walk_to_reconciled(plan_id)

    run = validate_success(api.get_reconciliation_run(run["id"], ADMIN), 200)
    row_z = get_results_row(run, tz["id"])
    assert row_z["top_down_cents"] == 0
    assert row_z["bottom_up_cents"] == 400000
    assert row_z["final_cents"] == 400000
    assert row_z["escalated"] is True
    assert row_z["deviation_pct"] is None

    row_y = get_results_row(run, ty["id"])
    assert row_y["top_down_cents"] == 1000000
    assert row_y["bottom_up_cents"] is None
    assert row_y["final_cents"] == 1000000
    assert row_y["escalated"] is False

    row_r = get_results_row(run, fx["root"]["id"])
    assert row_r["final_cents"] == 1000000


def test_reconciliation_blended_final_is_midpoint(api):
    """PRD: "otherwise, when the absolute gap times one hundred is less than or
    equal to the top-down figure times ten — a tolerance test performed in
    integer arithmetic exactly as written, with no rounding — the final is the
    midpoint of the two figures rounded half-up to whole cents and the row does
    not escalate"
    PRD: "Identical inputs can therefore produce different finals under the two
    policies."

    Identical inputs (top_down 1000000, bottom_up 1080000, deviation 8.00%
    within tolerance) land the child at 1040000 under BLENDED.

    Design: Difficulty/dual_variant_calc/reconciliation_blended_vs_top_down_wins
    """
    plans = setup_dual_reconciliation_policy_plans()
    pb = plans["b"]
    child_b = get_territory(pb["child"]["id"])
    assert child_b["final_quota_cents"] == 1040000, \
        "BLENDED midpoint of 1000000 and 1080000"
    run_b = validate_success(api.get_reconciliation_run(pb["run"]["id"],
                                                        ADMIN), 200)
    assert run_b["policy_used"] == "BLENDED"
    row = get_results_row(run_b, pb["child"]["id"])
    assert row["final_cents"] == 1040000
    assert row["deviation_pct"] == pytest.approx(8.00, abs=0.005)
    assert row["escalated"] is False


def test_reconciliation_top_down_wins_ignores_in_tolerance_submission(api):
    """PRD: "Under the `TOP_DOWN_WINS` variant the final is always the top-down
    figure and the bottom-up figure only sets the escalation flag"
    PRD: "Identical inputs can therefore produce different finals under the two
    policies."

    The identical inputs (top_down 1000000, bottom_up 1080000) leave the child
    at 1000000 under TOP_DOWN_WINS, with the in-tolerance row not escalated.

    Design: Difficulty/dual_variant_calc/reconciliation_blended_vs_top_down_wins
    """
    plans = setup_dual_reconciliation_policy_plans()
    pt = plans["t"]
    child_t = get_territory(pt["child"]["id"])
    assert child_t["final_quota_cents"] == 1000000, \
        "TOP_DOWN_WINS ignores the in-tolerance submission"
    run_t = validate_success(api.get_reconciliation_run(pt["run"]["id"],
                                                        ADMIN), 200)
    assert run_t["policy_used"] == "TOP_DOWN_WINS"
    row = get_results_row(run_t, pt["child"]["id"])
    assert row["final_cents"] == 1000000
    assert row["deviation_pct"] == pytest.approx(8.00, abs=0.005)
    assert row["escalated"] is False


def test_occ_reconciliation_apply_stale_version_rejected(api):
    """PRD: "Each of these requests must carry the field
    `expected_plan_year_version`, holding the plan version the client last
    observed; the field is non-optional on exactly these three operations. When
    the supplied value does not match the plan's current `version`, the request
    is rejected with `ERR_STALE_VERSION` (HTTP 412)."

    Stale apply is rejected 412 with the run still COMPUTED and the plan still
    SUBMISSIONS_CLOSED; the correct version applies and reconciles the plan.

    Design: Corner/cross_cutting_complexity_layers/occ_reconciliation_apply_stale_version_rejected
    """
    base = setup_open_plan(label="FY27-OCCR")
    plan_id = base["plan"]["id"]
    close_submissions(plan_id)
    run = compute_run(plan_id)
    pv = plan_version(plan_id)

    validate_error(api.apply_reconciliation_run(run["id"], pv - 1, ADMIN),
                   ApiErrorId.ERR_STALE_VERSION, 412)
    assert validate_success(api.get_reconciliation_run(run["id"], ADMIN),
                            200)["status"] == "COMPUTED"
    assert get_plan(plan_id)["status"] == "SUBMISSIONS_CLOSED"

    applied = validate_success(api.apply_reconciliation_run(run["id"], pv,
                                                            ADMIN), 200)
    assert applied["status"] == "APPLIED"
    assert get_plan(plan_id)["status"] == "RECONCILED"
