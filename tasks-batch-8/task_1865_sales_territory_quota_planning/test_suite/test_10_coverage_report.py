"""Coverage report: headcount ceil boundary (observed through the PRD-named
report header and territory quota fields) and the report's role gate."""
from test_helpers import (
    ADMIN,
    ApiErrorId,
    apply_allocation,
    create_allocation,
    create_plan,
    create_rep,
    get_territory,
    make_analyst_headers,
    make_sales_rep_headers,
    setup_open_plan_with_children,
    validate_error,
    validate_success,
)


def _setup_coverage_boundary_plan(api):
    """Plan OPEN with root R (potential 0) and ACTIVE children A then B, both
    potential 1; company target 6000001 allocated from R, so A (created
    earlier) receives 3000001 and B 3000000. No accounts, no reps."""
    fx = setup_open_plan_with_children(potentials=(1, 1), target=6000001,
                                       productivity=1500000,
                                       label="FY27-COV")
    alloc = create_allocation(fx["plan"]["id"], fx["root"]["id"], 6000001)
    apply_allocation(alloc["id"], fx["plan"]["id"])
    return fx


def test_coverage_headcount_exact_multiple_boundary(api):
    """PRD: "when retained quota is positive, the required headcount is
    retained divided by the plan's `productivity_per_rep_cents` rounded up to a
    whole head — with exact multiples dividing evenly, so a retained quota of
    exactly three times per-rep productivity requires exactly three heads, not
    four — and zero when retained is zero."
    PRD: "The report's header carries the `plan_year_id`, a `territory_count`,
    the plan-wide `uncovered_account_count` — accounts whose
    `assigned_territory_id` is null — and the `total_required_headcount` and
    `total_active_assignments` summed over the reported `rows`."

    Retained 3000001 (one cent over the exact multiple 2 x 1500000) requires 3
    heads; retained 3000000 divides evenly and requires exactly 2; the root's
    retained 0 requires 0 — so the plan-wide total is 3 + 2 + 0 == 5 (an
    off-by-one at the exact multiple would show up as 6).

    Design: Difficulty/boundary_precision_check/coverage_headcount_exact_multiple_boundary
    """
    fx = _setup_coverage_boundary_plan(api)
    ta, tb = (c["id"] for c in fx["children"])
    # The largest-remainder tie between equal raw shares breaks by creation
    # order, so A lands one cent over B (both raw shares 3000000.5).
    assert get_territory(ta)["assigned_quota_cents"] == 3000001
    assert get_territory(tb)["assigned_quota_cents"] == 3000000
    assert get_territory(fx["root"]["id"])["assigned_quota_cents"] == 6000001

    report = validate_success(
        api.get_coverage_report(fx["plan"]["id"], ADMIN), 200)
    assert report["plan_year_id"] == fx["plan"]["id"]
    assert report["territory_count"] == 3
    assert report["total_required_headcount"] == 5, \
        "3 (one cent over 2 x productivity) + 2 (exact multiple) + 0 " \
        "(root retained 0)"
    assert report["total_active_assignments"] == 0
    assert report["uncovered_account_count"] == 0
    assert len(report["rows"]) == 3


def test_coverage_headcount_boundary_report_totals_only(api):
    """PRD: "when retained quota is positive, the required headcount is
    retained divided by the plan's `productivity_per_rep_cents` rounded up to a
    whole head — with exact multiples dividing evenly, so a retained quota of
    exactly three times per-rep productivity requires exactly three heads, not
    four — and zero when retained is zero."

    Companion reading of the same boundary: with productivity 1500000 and the
    children holding 3000001 / 3000000, the summed requirement is 5 with zero
    staffed heads — the ceil rule verified through the PRD-named report header.

    Design: Difficulty/boundary_precision_check/coverage_headcount_exact_multiple_boundary
    """
    fx = _setup_coverage_boundary_plan(api)
    report = validate_success(
        api.get_coverage_report(fx["plan"]["id"], ADMIN), 200)
    assert report["total_required_headcount"] == 5
    assert report["total_active_assignments"] == 0
    assert report["uncovered_account_count"] == 0


def test_coverage_report_forbidden_for_rep_and_analyst(api):
    """PRD: "Available to administrators and revenue operations managers, it
    walks every territory in the plan whose `assigned_quota_cents` has been
    set, in territory creation order, and models headcount against retained
    quota."
    PRD: "Every endpoint declares which of these roles may call it (see §4); a
    caller whose role is not listed, or who fails an ownership check declared
    for the operation, is rejected with `ERR_FORBIDDEN_FOR_ROLE` (HTTP 403)."

    SalesRep and SalesOpsAnalyst are both denied the coverage report.

    Design: Corner/rbac/coverage_report_forbidden_for_rep_and_analyst
    """
    plan = create_plan(label="FY27-RB")
    rep = create_rep()
    validate_error(
        api.get_coverage_report(plan["id"],
                                make_sales_rep_headers(rep["id"])),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
    validate_error(
        api.get_coverage_report(plan["id"],
                                make_analyst_headers("analyst-1")),
        ApiErrorId.ERR_FORBIDDEN_FOR_ROLE, 403)
