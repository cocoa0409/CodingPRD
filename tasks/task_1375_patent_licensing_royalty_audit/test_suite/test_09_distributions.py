"""Distribution runs: share allocation rounding, pool conservation,
maker-checker SoD, fiscal guards, and temporal gates (PRD sections 2.8, 3.9)."""
from test_helpers import (
    ApiErrorId,
    approve_run,
    create_active_agreement,
    create_draft_run,
    create_licensee,
    get_agreement,
    make_finance_headers,
    setup_agreement_with_pool,
    setup_posted_run,
    validate_error,
    validate_success,
)


def test_inventor_share_rounding_remainder(api, finance_headers):
    """PRD section 3.9: "Each line's preliminary amount is the run's
    `pool_cents` multiplied by that inventor's `share_bp` over ten thousand,
    rounded half-up. The remainder is the pool minus the sum of the
    preliminary amounts — a small integer, never larger in magnitude than the
    number of shares. If the remainder is positive, one cent is added to each
    of the first `remainder` entries when the shares are ordered by `share_bp`
    descending with ties broken by `inventor_name` in ascending lexicographic
    order. ... The invariant is exact: the line amounts sum to `pool_cents`,
    cent for cent."

    Design: Difficulty/combinatorial_formula/inventor_share_rounding_remainder
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-40400-C1",
        base_rate_bp=500,
        underreport_tolerance_bp=1000,
        inventor_shares=[{"inventor_name": "Ann", "share_bp": 3333},
                         {"inventor_name": "Ben", "share_bp": 3333},
                         {"inventor_name": "Cid", "share_bp": 3334}],
    )
    from test_helpers import create_accepted_report, make_report_line
    create_accepted_report(
        agreement, licensee,
        lines=[make_report_line(product_label="X", gross_sales_cents=200_020)],
    )
    # Pool is now exactly 10001 (200020 * 5%).
    run = create_draft_run(agreement, 10_001)
    resp = api.approve_distribution_run(run["id"], make_finance_headers("fin-2"))
    posted = validate_success(resp)
    assert posted["status"] == "POSTED"

    lines = posted["lines"]
    by_name = {l["inventor_name"]: l["amount_cents"] for l in lines}
    # Per-line round_half_up: 10001*3333/10000 = 3333.3333 -> 3333 for Ann and
    # Ben; 10001*3334/10000 = 3334.3334 -> 3334 for Cid. Preliminary sum is
    # 10000, remainder +1 assigned to the largest share_bp (Cid).
    assert by_name["Ann"] == 3333
    assert by_name["Ben"] == 3333
    assert by_name["Cid"] == 3335
    assert sum(by_name.values()) == 10_001

    agreement_after = get_agreement(agreement["id"])
    assert agreement_after["undistributed_pool_cents"] == 0


def test_inventor_share_sum_exact_invariant(api):
    """PRD section 3.9: "The invariant is exact: the line amounts sum to
    `pool_cents`, cent for cent."

    Design: Difficulty/combinatorial_formula/inventor_share_rounding_remainder
    """
    ctx = setup_posted_run(
        pool_cents=5000, royalty_cents=5000,
        patent_reference="US-40401-C2",
        inventor_shares=[{"inventor_name": "Ada", "share_bp": 6000},
                         {"inventor_name": "Alan", "share_bp": 4000}],
    )
    run = ctx["run"]
    lines = run["lines"]
    assert sum(l["amount_cents"] for l in lines) == 5000
    by_name = {l["inventor_name"]: l["amount_cents"] for l in lines}
    assert by_name["Ada"] == 3000
    assert by_name["Alan"] == 2000


def test_distribution_approve_void_pool_conservation(api):
    """PRD section 3.9: "Approval also stamps `approved_by_user_id`, debits
    `pool_cents` from the agreement's `undistributed_pool_cents`, moves the
    run to `POSTED`, and increments its `version`." and "voiding a `POSTED`
    run — the request carries a `reason` — moves it to the terminal `VOIDED`
    status and restores the pool by adding `pool_cents` back to the
    agreement's `undistributed_pool_cents`."

    Design: Difficulty/compensating_invariant/distribution_approve_void_pool_conservation
    """
    ctx = setup_agreement_with_pool(
        royalty_cents=5000, patent_reference="US-88888-R1",
        inventor_shares=[{"inventor_name": "Ada", "share_bp": 6000},
                         {"inventor_name": "Alan", "share_bp": 4000}],
    )
    agreement = ctx["agreement"]
    run = create_draft_run(agreement, 5000)

    approve_run(run["id"])
    assert get_agreement(agreement["id"])["undistributed_pool_cents"] == 0

    resp = api.void_distribution_run(run["id"], {"reason": "posted in error"},
                                     make_finance_headers("fin-2"))
    voided = validate_success(resp)
    assert voided["status"] == "VOIDED"
    # Approve+void round trip conserves the undistributed pool.
    assert get_agreement(agreement["id"])["undistributed_pool_cents"] == 5000


def test_distribution_posted_lines_frozen_and_pool_debited(api):
    """PRD section 3.9: "Approval freezes the run's `lines`: one per entry of
    the agreement's `inventor_shares`, preserving that array's order ... The
    invariant is exact: the line amounts sum to `pool_cents`, cent for cent."
    and "debits `pool_cents` from the agreement's `undistributed_pool_cents`".

    Design: Difficulty/compensating_invariant/distribution_approve_void_pool_conservation
    """
    ctx = setup_agreement_with_pool(
        royalty_cents=5000, patent_reference="US-88889-R2",
        inventor_shares=[{"inventor_name": "Ada", "share_bp": 6000},
                         {"inventor_name": "Alan", "share_bp": 4000}],
    )
    run = create_draft_run(ctx["agreement"], 5000)
    posted = approve_run(run["id"])

    assert posted["status"] == "POSTED"
    by_name = {l["inventor_name"]: l["amount_cents"] for l in posted["lines"]}
    assert by_name == {"Ada": 3000, "Alan": 2000}
    assert sum(by_name.values()) == 5000
    assert get_agreement(ctx["agreement"]["id"])["undistributed_pool_cents"] == 0


def test_temporal_vs_fiscal_on_run_create(api, finance_headers):
    """PRD section 2.8: "Every request is validated against an ordered
    pipeline of check tiers. A request that fails an earlier tier never
    surfaces an error from a later tier — the first failing tier determines
    the response." Tier 11 is "Temporal rules. Periods must be closed ...
    `ERR_PERIOD_NOT_CLOSED`" and tier 13 is "Fiscal guards. Last, the
    money-shaping rules: ... `ERR_POOL_EXCEEDS_UNDISTRIBUTED`". PRD section
    3.9: "a `period_end` later than the current logical time is rejected with
    `ERR_PERIOD_NOT_CLOSED`."

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_run_create
    """
    ctx = setup_agreement_with_pool(
        royalty_cents=5000, patent_reference="US-11111-J1"
    )
    # Both violations: period_end in the future AND pool exceeds undistributed.
    resp = api.create_distribution_run(
        {"agreement_id": ctx["agreement"]["id"],
         "period_start": "2026-08-01T00:00:00Z",
         "period_end": "2026-12-31T00:00:00Z",
         "pool_cents": 999_999},
        finance_headers,
    )
    # Temporal (tier 11) fires before fiscal (tier 13).
    validate_error(resp, ApiErrorId.ERR_PERIOD_NOT_CLOSED)


def test_fiscal_fires_when_temporal_passes(api, finance_headers):
    """PRD section 2.8: "A request that fails an earlier tier never surfaces
    an error from a later tier — the first failing tier determines the
    response." PRD section 3.9: "The pool must be strictly greater than 0 and
    must not exceed the agreement's `undistributed_pool_cents` at creation; an
    oversized pool is rejected with `ERR_POOL_EXCEEDS_UNDISTRIBUTED` (HTTP
    422)." With a closed period, the fiscal guard is the first failing tier.

    Design: Difficulty/priority_pair_validation_conflict/temporal_vs_fiscal_on_run_create
    """
    ctx = setup_agreement_with_pool(
        royalty_cents=5000, patent_reference="US-11112-J2"
    )
    resp = api.create_distribution_run(
        {"agreement_id": ctx["agreement"]["id"],
         "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z",
         "pool_cents": 6000},
        finance_headers,
    )
    validate_error(resp, ApiErrorId.ERR_POOL_EXCEEDS_UNDISTRIBUTED)


def test_pool_exceeds_undistributed_single_violation(api, finance_headers):
    """PRD section 3.9: "The pool must be strictly greater than 0 and must
    not exceed the agreement's `undistributed_pool_cents` at creation; an
    oversized pool is rejected with `ERR_POOL_EXCEEDS_UNDISTRIBUTED` (HTTP
    422)."

    Design: Corner/validations/pool_exceeds_undistributed_single_violation
    """
    ctx = setup_agreement_with_pool(
        royalty_cents=5000, patent_reference="US-23242-M2"
    )
    resp = api.create_distribution_run(
        {"agreement_id": ctx["agreement"]["id"],
         "period_start": "2026-03-01T00:00:00Z",
         "period_end": "2026-03-31T00:00:00Z",
         "pool_cents": 6000},
        finance_headers,
    )
    validate_error(resp, ApiErrorId.ERR_POOL_EXCEEDS_UNDISTRIBUTED)


def test_reapprove_posted_run_invalid_state(api, finance_headers):
    """PRD section 3.9: "A `FinanceOfficer` approves a `DRAFT` run — anything
    else draws `ERR_RUN_INVALID_STATE` (HTTP 409)".

    Design: Corner/errors/reapprove_posted_run_invalid_state
    """
    ctx = setup_posted_run(
        pool_cents=5000, royalty_cents=5000, patent_reference="US-34353-N2"
    )
    resp = api.approve_distribution_run(ctx["run"]["id"], make_finance_headers("fin-3"))
    validate_error(resp, ApiErrorId.ERR_RUN_INVALID_STATE)
    # The pool is not re-debited.
    assert get_agreement(ctx["agreement"]["id"])["undistributed_pool_cents"] == 0


def test_sod_finance_approve_own_run(api, finance_headers):
    """PRD section 3.9: "the approver must not be the run's creator: if the
    caller's identity equals `created_by_user_id`, the approval is rejected
    with `ERR_SOD_CONFLICT`."

    Design: Corner/rbac/sod_finance_approve_own_run
    """
    ctx = setup_agreement_with_pool(
        royalty_cents=5000, patent_reference="US-11120-U2"
    )
    run = create_draft_run(ctx["agreement"], 5000, creator_headers=finance_headers)

    # The creator cannot approve their own run.
    resp = api.approve_distribution_run(run["id"], finance_headers)
    validate_error(resp, ApiErrorId.ERR_SOD_CONFLICT)

    # A different officer approves.
    posted = approve_run(run["id"], make_finance_headers("fin-2"))
    assert posted["status"] == "POSTED"
    assert posted["approved_by_user_id"] == "fin-2"
