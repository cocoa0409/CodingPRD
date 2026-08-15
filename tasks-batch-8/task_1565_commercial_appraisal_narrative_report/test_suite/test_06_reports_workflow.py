"""Report production: versioning and supersession, optimistic concurrency on
engagement version, review cycles, the reconciliation rounding order, and
the weight-sum gate (PRD §2.5, §2.7, §3.6, §3.7)."""
from test_helpers import (
    TEST_USERS,
    add_approach,
    add_data_submission,
    add_income_approach,
    add_support_comparables,
    add_revision_request,
    create_draft_report,
    create_engagement,
    create_in_progress_engagement,
    create_parties,
    fresh_engagement,
    setup_report_client_review,
    setup_report_internal_review,
    validate_error,
    validate_success,
)

EM = TEST_USERS["engagement_manager_headers"]

STMT_2025 = dict(
    submission_type="OPERATING_STATEMENT",
    period_start="2025-01-01T00:00:00Z",
    period_end="2025-12-31T00:00:00Z",
    scheduled_gross_rent_cents=12000000,
    vacancy_loss_cents=600000,
    expense_reimbursements_cents=300000,
    operating_expenses_cents=4000000,
)


def test_report_version_supersede_side_effects(api):
    """PRD §3.6: "Creation assigns `report_version_no` as one greater than
    the highest existing version on the engagement, so the first report is
    version one. Creation also supersedes the past: every existing report of
    the engagement still in a non-terminal state — `DRAFTING`,
    `INTERNAL_REVIEW`, `REVIEWED`, `CLIENT_REVIEW`, `REVISION_REQUESTED`,
    `FINAL`, or `SIGNED` — moves to `SUPERSEDED`, and the new report's
    `supersedes_report_id` points at the superseded report holding the
    greatest version number, remaining null when there was nothing to
    supersede, as for version one."

    Design: Corner/state_machines/report_version_supersede_side_effects
    """
    bundle = create_in_progress_engagement()
    rep1 = create_draft_report(bundle)
    assert rep1["report_version_no"] == 1
    assert rep1.get("supersedes_report_id") is None
    rep2 = create_draft_report(bundle)
    rep1_after = validate_success(api.get_report(rep1["id"], EM), 200)
    assert rep1_after["status"] == "SUPERSEDED"
    assert rep2["report_version_no"] == 2
    assert rep2["supersedes_report_id"] == rep1["id"]
    assert rep2["status"] == "DRAFTING"


def test_occ_report_create_stale_version_rejected(api):
    """PRD §3.6: "the create is one of the two optimistic-concurrency writes
    of §2.7: the request must carry `expected_engagement_version` matching
    the engagement's current `version`, else it is rejected with
    `ERR_STALE_ENGAGEMENT_VERSION` (HTTP 412)."

    Design: Corner/cross_cutting_complexity_layers/occ_report_create_stale_version
    """
    bundle = create_in_progress_engagement()
    eng = fresh_engagement(bundle)
    rep1 = validate_success(api.create_report(
        eng["id"], {"expected_engagement_version": eng["version"]},
        bundle["author_headers"]), 201)
    assert rep1["status"] == "DRAFTING"
    res = api.create_report(
        eng["id"], {"expected_engagement_version": eng["version"]},
        bundle["author_headers"])
    validate_error(res, "ERR_STALE_ENGAGEMENT_VERSION", expected_status=412)


def test_occ_report_create_retry_with_fresh_version(api):
    """PRD §2.7: "If the engagement's current `version` has advanced since
    that observation — most commonly because an earlier report creation on
    the same engagement legitimately superseded prior versions and bumped the
    engagement — the create is rejected with `ERR_STALE_ENGAGEMENT_VERSION`
    (HTTP 412), forcing the client to re-read before minting another version
    on state it has not seen." After re-reading, the retry succeeds and is
    version two per §3.6.

    Design: Corner/cross_cutting_complexity_layers/occ_report_create_stale_version
    """
    bundle = create_in_progress_engagement()
    eng = fresh_engagement(bundle)
    validate_success(api.create_report(
        eng["id"], {"expected_engagement_version": eng["version"]},
        bundle["author_headers"]), 201)
    eng_fresh = fresh_engagement(bundle)
    rep2 = validate_success(api.create_report(
        eng_fresh["id"],
        {"expected_engagement_version": eng_fresh["version"]},
        bundle["author_headers"]), 201)
    assert rep2["report_version_no"] == 2


def test_version_increments_one_per_mutation(api):
    """PRD §2.5: "A system-managed integer that increments with every
    modification to the resource" and "creating a new report version bumps
    the parent engagement's `version`". Submit, accept, and report creation
    each increment the engagement's version by exactly one.

    Design: Corner/cross_cutting_complexity_layers/version_increments_on_mutations
    """
    parties = create_parties()
    eng = create_engagement(parties)
    v_create = eng["version"]
    eng = validate_success(api.submit_engagement(eng["id"], EM), 200)
    assert eng["version"] == v_create + 1, (
        f"submit must increment version by one: {v_create} -> {eng['version']}")
    v_submit = eng["version"]
    eng = validate_success(
        api.accept_engagement(eng["id"], parties["client_headers"]), 200)
    assert eng["version"] == v_submit + 1, (
        f"accept must increment version by one: {v_submit} -> {eng['version']}")
    bundle = {**parties, "engagement": eng}
    validate_success(api.create_report(
        eng["id"], {"expected_engagement_version": eng["version"]},
        bundle["author_headers"]), 201)
    eng_after = fresh_engagement(bundle)
    assert eng_after["version"] == eng["version"] + 1, (
        "report creation must bump the engagement version by exactly one")


def test_report_review_return_increments_cycle_count(api):
    """PRD §3.6: "Return sends the report from `INTERNAL_REVIEW` back to
    `DRAFTING` — the reviewer supplies a `review_note` describing the
    deficiencies — and increments `review_cycle_count`, so the file records
    how many times the draft has been sent back."

    Design: Difficulty/non_linear_state_machine/report_review_and_client_revision_cycles
    """
    bundle = setup_report_internal_review()
    report = bundle["report"]
    returned = validate_success(api.review_return(
        report["id"], {"review_note": "Rework cap support narrative"},
        bundle["reviewer_headers"]), 200)
    assert returned["status"] == "DRAFTING"
    assert returned["review_cycle_count"] == 1


def test_report_client_revision_cycle_closes(api):
    """PRD §3.7: "A new request stands `OPEN`, stamps its own
    `submitted_at`, and its creation automatically moves the report from
    `CLIENT_REVIEW` to `REVISION_REQUESTED`." and "Reissuing the report —
    `REVISION_REQUESTED` back to `CLIENT_REVIEW` — requires that no request
    on the report remain `OPEN` (`ERR_REVISION_REQUESTS_OPEN`) and refreshes
    `issued_to_client_at`, restarting the thirty-day window." Declining the
    request (§3.7: "from `OPEN` the author declines") clears the way.

    Design: Difficulty/non_linear_state_machine/report_review_and_client_revision_cycles
    """
    bundle = setup_report_client_review()
    req = add_revision_request(
        bundle, category="FACTUAL_CORRECTION",
        requested_change="Fix year built typo")
    assert req["status"] == "OPEN"
    assert bundle["report"]["status"] == "REVISION_REQUESTED"

    declined = validate_success(api.decline_revision_request(
        req["id"], {"resolution_note": "Year built already correct per assessor"},
        bundle["author_headers"]), 200)
    assert declined["status"] == "DECLINED"

    reissued = validate_success(
        api.reissue_report(bundle["report"]["id"], bundle["author_headers"]), 200)
    assert reissued["status"] == "CLIENT_REVIEW", (
        "reissue after the only request was declined must close the cycle")


def test_weight_sum_exact_100_passes(api):
    """PRD §3.6: "the `weight_pct` values of exactly those included
    approaches must sum to exactly 100.00 (`ERR_WEIGHT_SUM_INVALID`)" — a
    single COMPLETE approach at weight 100.00 satisfies the gate and the
    draft moves to `INTERNAL_REVIEW`.

    Design: Difficulty/boundary_precision_check/weight_sum_exact_100_boundary
    """
    bundle = setup_report_internal_review()
    assert bundle["report"]["status"] == "INTERNAL_REVIEW"
    assert bundle["report"]["value_conclusion_cents"] == 106571429


def test_weight_sum_99_99_rejected(api):
    """PRD §3.6: "the `weight_pct` values of exactly those included
    approaches must sum to exactly 100.00 (`ERR_WEIGHT_SUM_INVALID`)" — a
    single COMPLETE approach at weight 99.99 sums below 100.00 and the
    submission to review is rejected.

    Design: Difficulty/boundary_precision_check/weight_sum_exact_100_boundary
    """
    bundle = create_in_progress_engagement()
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    add_income_approach(bundle, complete=True, weight_pct=99.99)
    report = create_draft_report(bundle)
    res = api.submit_review(report["id"], bundle["author_headers"])
    validate_error(res, "ERR_WEIGHT_SUM_INVALID", expected_status=409)


def test_reconciled_value_rounds_per_approach_then_sums(api):
    """PRD §3.6: "The snapshot then computes `value_conclusion_cents` as a
    weighted reconciliation with pinned rounding: each included approach
    contributes its `indicated_value_cents` multiplied by its `weight_pct`
    hundredths, rounded half-up to whole cents first, and the conclusion is
    the integer sum of those rounded contributions. Summing unrounded
    products and rounding once at the end yields a different cent total and
    is non-conforming." Indicated values 106,571,429 / 58,800,000 /
    21,000,002 at weights 40.00/30.00/30.00 give 42,628,572 + 17,640,000 +
    6,300,001 = 66,568,573.

    Design: Difficulty/combinatorial_formula/reconciled_value_round_per_approach_then_sum_mode_b
    """
    bundle = create_in_progress_engagement(planned_approach_count=3)
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    add_approach(bundle, complete=True, approach_type="INCOME",
                 weight_pct=40.00, cap_rate_bps=700)
    add_approach(bundle, complete=True, approach_type="SALES_COMPARISON",
                 weight_pct=30.00)
    add_approach(bundle, complete=True, approach_type="COST",
                 weight_pct=30.00, land_value_cents=20000002,
                 replacement_cost_cents=1000000, depreciation_pct=0)
    report = create_draft_report(bundle)
    submitted = validate_success(
        api.submit_review(report["id"], bundle["author_headers"]), 200)
    assert submitted["value_conclusion_cents"] == 66568573, (
        "round-per-approach-then-sum must yield 66568573 (sum-then-round "
        f"66568572 is non-conforming), got {submitted['value_conclusion_cents']}")
    assert submitted["status"] == "INTERNAL_REVIEW"


def test_reconciled_value_snapshot_persists(api):
    """PRD §3.6: "Submitting a draft to internal review moves it from
    `DRAFTING` to `INTERNAL_REVIEW` and snapshots the reconciled value
    conclusion." The snapshot stored on the report remains readable at
    66,568,573 after the transition.

    Design: Difficulty/combinatorial_formula/reconciled_value_round_per_approach_then_sum_mode_b
    """
    bundle = create_in_progress_engagement(planned_approach_count=3)
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    add_approach(bundle, complete=True, approach_type="INCOME",
                 weight_pct=40.00, cap_rate_bps=700)
    add_approach(bundle, complete=True, approach_type="SALES_COMPARISON",
                 weight_pct=30.00)
    add_approach(bundle, complete=True, approach_type="COST",
                 weight_pct=30.00, land_value_cents=20000002,
                 replacement_cost_cents=1000000, depreciation_pct=0)
    report = create_draft_report(bundle)
    validate_success(
        api.submit_review(report["id"], bundle["author_headers"]), 200)
    persisted = validate_success(api.get_report(report["id"], EM), 200)
    assert persisted["value_conclusion_cents"] == 66568573
    assert persisted["status"] == "INTERNAL_REVIEW"


def test_report_deliver_before_sign_returns_409(api):
    """PRD §3.8: "Delivery is the engagement's point of no return, performed
    by a `StaffAppraiser` or the `EngagementManager`, moving the report from
    `SIGNED` to `DELIVERED` and stamping `delivered_at`." A report standing
    `FINAL` is not in the delivery from-state and rejects with
    `ERR_INVALID_STATE_TRANSITION` (§2.9).

    Design: Corner/state_machines/report_deliver_before_sign_returns_409
    """
    parties = create_parties(with_signer=True)
    bundle = create_in_progress_engagement(parties)
    add_data_submission(bundle, accept=True, **STMT_2025)
    add_support_comparables(bundle)
    add_income_approach(bundle, complete=True)
    report = create_draft_report(bundle)
    validate_success(
        api.submit_review(report["id"], bundle["author_headers"]), 200)
    validate_success(
        api.review_approve(report["id"], bundle["reviewer_headers"]), 200)
    validate_success(
        api.issue_to_client(report["id"], bundle["author_headers"]), 200)
    final = validate_success(
        api.finalize_report(report["id"], bundle["author_headers"]), 200)
    assert final["status"] == "FINAL"
    res = api.deliver_report(report["id"], bundle["author_headers"])
    validate_error(res, "ERR_INVALID_STATE_TRANSITION", expected_status=409)
