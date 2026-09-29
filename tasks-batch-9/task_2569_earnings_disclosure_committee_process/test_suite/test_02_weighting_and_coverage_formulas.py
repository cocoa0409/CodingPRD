"""Three nested formulas whose evaluation order is pinned by the contract.

A sub-certification's weight nests a base, an officer factor and an escalation
factor before a cap; the cycle's coverage sums raw weights before dividing; and
a tie-out line's verdict consumes a document-wide tier derived from the whole
line set.
"""

from prd_bench_local_runner.testing import validate_success
from test_helpers.assertions import assert_integer, assert_money, assert_two_decimal_places
from test_helpers.fixtures import (
    add_tie_out,
    assign_subcert,
    build_committee,
    open_close,
    build_cycle,
    add_milestone,
    readiness,
    refresh_cycle,
    refresh_document,
    scenario_close_open,
    submit_subcert,
)
from test_helpers.test_users import admin_headers

WEIGHTING_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("ceo", "Rhea Chief", "FINANCE", True, True),
    ("cfo", "Sam Fiscal", "FINANCE", True, True),
]
COVERAGE_SEATS = [
    ("fin", "Nora Finance", "FINANCE", False, True),
    ("legal", "Owen Legal", "LEGAL", False, True),
]
SOLE_FINANCE_SEAT = [("fin", "Nora Finance", "FINANCE", False, True)]


def _open_cycle(api, committee):
    """A cycle whose close is open, carrying one planned close window."""
    cycle = build_cycle(api, committee)
    add_milestone(
        api, committee, cycle["id"], "CLOSE", "2026-08-01T00:00:00Z", "2026-08-03T00:00:00Z"
    )
    open_close(api, committee, cycle["id"])
    return cycle


def _weighting_fixture(api):
    committee = build_committee(
        api,
        seats=WEIGHTING_SEATS,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Weighting Charter",
        chair_key="fin",
    )
    cycle = _open_cycle(api, committee)
    rows = {
        "ops": assign_subcert(
            api, committee, cycle["id"], "ceo", "OPERATIONS",
            due_utc="2026-08-04T12:00:00Z", chair_key="fin",
        ),
        "rev": assign_subcert(
            api, committee, cycle["id"], "cfo", "REVENUE",
            due_utc="2026-08-04T12:00:00Z", chair_key="fin",
        ),
        "plain": assign_subcert(
            api, committee, cycle["id"], "fin", "OPERATIONS",
            due_utc="2026-08-04T12:00:00Z", chair_key="fin",
        ),
    }
    return committee, cycle, rows


def test_officer_factor_lifts_the_base_and_the_cap_already_binds_on_revenue(api):
    """At creation the officer factor multiplies the scope base: an officer's
    operations row reads 30.00 while an officer's revenue row reads exactly
    45.00 because 30 * 1.5 lands on the cap, and a non-officer's operations row
    stays at its base 20.00.

    PRD 3.4: "That base is multiplied by an officer-support factor of 1.5 when the named member's `is_officer` flag is true, and by 1.0 otherwise."

    Design: Difficulty/combinatorial_formula/subcert_scope_weight_officer_escalation_nesting_with_cap_applied_last
    """
    _, cycle, rows = _weighting_fixture(api)

    assert_money(rows["ops"]["scope_weight"], 30.00)
    assert_money(rows["rev"]["scope_weight"], 45.00)
    assert_money(rows["plain"]["scope_weight"], 20.00)
    for row in rows.values():
        assert row["status"] == "PENDING"
        assert row["exception_severity"] == "NONE"
        assert_two_decimal_places(row["scope_weight"])

    after = refresh_cycle(api, cycle["id"])
    assert_money(after["total_assigned_scope_weight"], 95.00)


def test_escalation_is_applied_before_the_cap_and_the_cap_only_once(api):
    """A LOW escalation moves an officer's operations row from 30.00 to 33.00,
    while a HIGH escalation on an officer's revenue row leaves it at exactly
    45.00 rather than at the unclamped product 90.00, and the clean submission
    leaves its own weight alone.

    PRD 3.4: "The order of the final three steps is pinned and matters: take the larger of the base weight and that product, round the result half up to two decimal places **once**, and only then cap it at 45."

    Design: Difficulty/combinatorial_formula/subcert_scope_weight_officer_escalation_nesting_with_cap_applied_last
    """
    committee, cycle, rows = _weighting_fixture(api)

    escalated_ops = submit_subcert(
        api, committee, rows["ops"]["id"], "ceo",
        exception_severity="LOW",
        exception_note="One immaterial cut-off exception in plant operations.",
    )
    escalated_rev = submit_subcert(
        api, committee, rows["rev"]["id"], "cfo",
        exception_severity="HIGH",
        exception_note="Revenue cut-off exception under investigation.",
    )
    clean = submit_subcert(api, committee, rows["plain"]["id"], "fin")

    assert escalated_ops["status"] == "EXCEPTION_NOTED"
    assert_money(escalated_ops["scope_weight"], 33.00)
    assert escalated_rev["status"] == "EXCEPTION_NOTED"
    assert_money(escalated_rev["scope_weight"], 45.00)
    assert clean["status"] == "SUBMITTED"
    assert_money(clean["scope_weight"], 20.00)

    after = refresh_cycle(api, cycle["id"])
    assert_money(after["total_assigned_scope_weight"], 98.00)
    assert_money(after["certification_coverage_pct"], 100.00)


def _coverage_fixture(api):
    committee = build_committee(
        api,
        seats=COVERAGE_SEATS,
        min_quorum_count=2,
        required_functions=["FINANCE", "LEGAL"],
        name="Coverage Charter",
    )
    cycle = _open_cycle(api, committee)
    rows = {
        "rev": assign_subcert(
            api, committee, cycle["id"], "fin", "REVENUE", due_utc="2026-08-04T12:00:00Z"
        ),
        "leg": assign_subcert(
            api, committee, cycle["id"], "legal", "LEGAL_CONTINGENCY",
            due_utc="2026-08-04T12:00:00Z",
        ),
        "ops": assign_subcert(
            api, committee, cycle["id"], "fin", "OPERATIONS", due_utc="2026-08-05T12:00:00Z"
        ),
        "ir": assign_subcert(
            api, committee, cycle["id"], "legal", "IR_COMMUNICATIONS",
            due_utc="2026-08-05T12:00:00Z",
        ),
    }
    return committee, cycle, rows


def test_coverage_sums_raw_weights_before_dividing_and_never_averages_percentages(api):
    """Four rows weighted 30.00 / 25.00 / 20.00 / 15.00 with only the first two
    submitted give 55 / 90 * 100 = 61.11, not the 50.00 an unweighted average of
    per-scope percentages would produce.

    PRD 3.4: "Computing a per-scope-area completion percentage, rounding each of those, and averaging them unweighted is explicitly forbidden and gives a different answer: for four requests weighted 30.00, 25.00, 20.00 and 15.00 with the first two submitted, the pinned order yields 61.11 while the forbidden order yields 50.00."

    Design: Difficulty/combinatorial_formula/certification_coverage_weighted_sum_before_division_not_average_of_percentages
    """
    committee, cycle, rows = _coverage_fixture(api)
    assert_money(rows["rev"]["scope_weight"], 30.00)
    assert_money(rows["leg"]["scope_weight"], 25.00)
    assert_money(rows["ops"]["scope_weight"], 20.00)
    assert_money(rows["ir"]["scope_weight"], 15.00)

    submitted_rev = submit_subcert(api, committee, rows["rev"]["id"], "fin")
    submitted_leg = submit_subcert(api, committee, rows["leg"]["id"], "legal")
    assert submitted_rev["status"] == "SUBMITTED"
    assert submitted_leg["status"] == "SUBMITTED"

    after = refresh_cycle(api, cycle["id"])
    assert_money(after["total_assigned_scope_weight"], 90.00)
    assert_money(after["certification_coverage_pct"], 61.11)
    assert abs(float(after["certification_coverage_pct"]) - 50.00) > 0.01

    still_pending = {
        key: validate_success(api.get_subcert(rows[key]["id"], admin_headers()))
        for key in ("ops", "ir")
    }
    assert still_pending["ops"]["status"] == "PENDING"
    assert still_pending["ir"]["status"] == "PENDING"


def test_an_all_pending_scope_reads_zero_and_the_dashboard_repeats_the_weighted_ratio(api):
    """Before any submission the numerator set is empty, so coverage reads 0.00
    against a 90.00 denominator; once the two heaviest rows are in, the
    readiness dashboard reports the same weighted 61.11 the cycle record does.

    PRD 3.4: "Otherwise the raw `scope_weight` values of the numerator set are summed, the raw `scope_weight` values of the denominator set are summed, the first sum is divided by the second, the quotient is multiplied by 100, and the result is rounded half up to two decimal places exactly once."

    Design: Difficulty/combinatorial_formula/certification_coverage_weighted_sum_before_division_not_average_of_percentages
    """
    committee, cycle, rows = _coverage_fixture(api)

    before = refresh_cycle(api, cycle["id"])
    assert_money(before["total_assigned_scope_weight"], 90.00)
    assert_money(before["certification_coverage_pct"], 0.00)

    submit_subcert(api, committee, rows["rev"]["id"], "fin")
    submit_subcert(api, committee, rows["leg"]["id"], "legal")

    dashboard = readiness(api, cycle["id"])
    assert dashboard["cycle_id"] == cycle["id"]
    assert_money(dashboard["total_assigned_scope_weight"], 90.00)
    assert_money(dashboard["certification_coverage_pct"], 61.11)
    assert_two_decimal_places(dashboard["certification_coverage_pct"])


def _tie_out_fixture(api):
    committee = build_committee(
        api,
        seats=SOLE_FINANCE_SEAT,
        min_quorum_count=1,
        required_functions=["FINANCE"],
        name="Tie-Out Charter",
        chair_key="fin",
    )
    scenario = scenario_close_open(api, committee)
    document = scenario.document(
        "PERIODIC_FILING", author_key="fin", title="Form 10-Q FY2026-Q2",
        safe_harbor_present=True,
    )
    first = add_tie_out(
        api, committee, document["id"], "Total revenue", 4120000, 4120000, tolerance_bp=25
    )
    second = add_tie_out(
        api, committee, document["id"], "Operating income", 812500, 812400, tolerance_bp=25
    )
    return committee, document, first, second


def _item(api, item_id):
    return validate_success(api.get_tie_out_item(item_id, admin_headers()))


def test_a_one_basis_point_schedule_stays_in_the_tight_tier_and_passes(api):
    """A 100-unit difference on an 812400 source record rounds to a raw variance
    of 1 basis point, and a document total of 1 basis point is at most 50, so the
    tier multiplier stays 1.00 and the schedule reads PASSED.

    PRD 3.6: "A total of at most 50 basis points earns the tight tier and a multiplier of 1.00."

    Design: Difficulty/combinatorial_formula/tie_out_tier_multiplier_recomputed_from_snapshot_total_across_whole_item_set
    """
    committee, document, first, second = _tie_out_fixture(api)

    assert_integer(second["raw_variance_bp"])
    assert second["raw_variance_bp"] == 1
    assert first["raw_variance_bp"] == 0

    after_two = refresh_document(api, committee, document["id"])
    assert after_two["tie_out_total_variance_bp"] == 1
    assert_money(after_two["tie_out_tier_multiplier"], 1.00)
    assert after_two["tie_out_status"] == "PASSED"
    assert _item(api, first["id"])["effective_tolerance_bp"] == 25
    assert _item(api, second["id"])["effective_tolerance_bp"] == 25


def test_a_third_line_retightens_the_two_already_matched_lines_through_the_tier(api):
    """A third line whose own raw variance is 81 basis points pushes the document
    total to 82, which crosses into the medium tier at 0.75 and retroactively
    tightens both earlier lines from an effective tolerance of 25 to
    floor(25 * 0.75) = 18, without touching either stored `tolerance_bp`.

    PRD 3.6: "**Step four** derives, for every item in the non-waived set, an `effective_tolerance_bp` equal to that item's own `tolerance_bp` multiplied by the document's tier multiplier and then floored to a whole number of basis points by truncation."

    Design: Difficulty/combinatorial_formula/tie_out_tier_multiplier_recomputed_from_snapshot_total_across_whole_item_set
    """
    committee, document, first, second = _tie_out_fixture(api)

    third = add_tie_out(
        api, committee, document["id"], "Diluted EPS", 1.24, 1.23, tolerance_bp=100
    )
    assert third["raw_variance_bp"] == 81

    after_three = refresh_document(api, committee, document["id"])
    assert after_three["tie_out_total_variance_bp"] == 82
    assert_money(after_three["tie_out_tier_multiplier"], 0.75)
    assert after_three["tie_out_status"] == "FAILED"

    row_one = _item(api, first["id"])
    row_two = _item(api, second["id"])
    row_three = _item(api, third["id"])
    assert row_one["raw_variance_bp"] == 0
    assert row_one["effective_tolerance_bp"] == 18
    assert row_one["status"] == "MATCHED"
    assert row_two["raw_variance_bp"] == 1
    assert row_two["effective_tolerance_bp"] == 18
    assert row_two["status"] == "MATCHED"
    assert row_three["raw_variance_bp"] == 81
    assert row_three["effective_tolerance_bp"] == 75
    assert row_three["status"] == "VARIANCE"
    assert row_one["tolerance_bp"] == 25
    assert row_two["tolerance_bp"] == 25
    assert row_three["tolerance_bp"] == 100
