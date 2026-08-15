"""Royalty report intake: provisional vs final royalty, base derivation with
sublicense lines, screening fork, boundaries, period overlap, conditional
schema, and fiscal guards (PRD sections 2.5, 3.5, 3.6)."""
from test_helpers import (
    ApiErrorId,
    accept_report,
    create_accepted_report,
    create_active_agreement,
    create_approved_grant,
    create_royalty_report_payload,
    create_validated_report,
    get_agreement,
    get_licensee,
    make_licensee_headers,
    make_report_line,
    submit_report,
    validate_error,
    validate_report,
    validate_success,
)


def test_provisional_vs_final_minimum_floor_binds(api, analyst_headers):
    """PRD section 3.6: "The `provisional_royalty_cents` is then computed with
    no minimum floor" and "`final_royalty_cents` is the greater of that sum and
    the agreement's `minimum_period_royalty_cents`." PRD section 2.9:
    "`outstanding_balance_cents` ... accumulates, in order of event kind: the
    final royalty of every accepted report".

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_minimum_floor
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-10123456-B2",
        minimum_period_royalty_cents=10_000,
        underreport_tolerance_bp=1000,
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(product_label="W1", units_sold=10,
                                gross_sales_cents=100_000)],
    )
    # PROVISIONAL: 5% of 100000 = 5000, no floor.
    assert report["provisional_royalty_cents"] == 5000

    validate_report(report["id"], benchmark_net_sales_cents=0)
    accepted = accept_report(report["id"])
    # FINAL: max(5000, minimum 10000) = 10000.
    assert accepted["status"] == "ACCEPTED"
    assert accepted["final_royalty_cents"] == 10_000

    licensee_after = get_licensee(licensee["id"])
    assert licensee_after["outstanding_balance_cents"] == 10_000


def test_provisional_vs_final_floor_not_binding_when_computed_higher(api, analyst_headers):
    """PRD section 3.6: "The `provisional_royalty_cents` is then computed with
    no minimum floor" and "`final_royalty_cents` is the greater of that sum and
    the agreement's `minimum_period_royalty_cents`." When the computed royalty
    exceeds the floor, provisional and final agree.

    Design: Difficulty/dual_variant_calc/royalty_provisional_vs_final_minimum_floor
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-10123457-B2",
        minimum_period_royalty_cents=10_00,
        underreport_tolerance_bp=1000,
    )
    report = create_accepted_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=100_000)],
    )
    # computed 5000 > floor 100: both variants agree at 5000.
    assert report["provisional_royalty_cents"] == 5000
    assert report["final_royalty_cents"] == 5000


def test_royalty_due_multi_input_branch(api, analyst_headers):
    """PRD section 3.6: "The `royalty_base_cents` follows the agreement's
    `royalty_base_definition` but counts only non-sublicense lines" and
    "`sublicense_net_sales_cents` sums gross minus deductions over the
    sublicense-revenue lines only. The `provisional_royalty_cents` is then
    computed with no minimum floor: the product component is
    `royalty_base_cents` multiplied by the effective rate ... over ten
    thousand, rounded half-up; the pass-through component is
    `sublicense_net_sales_cents` multiplied by
    `sublicense_passthrough_rate_bp` over ten thousand, rounded half-up; the
    provisional royalty is the sum of the two rounded components." and
    "`final_royalty_cents` is the greater of that sum and the agreement's
    `minimum_period_royalty_cents`."

    Design: Difficulty/combinatorial_formula/royalty_due_multi_input_branch
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-30300-B1",
        base_rate_bp=500,
        minimum_period_royalty_cents=20_000,
        sublicense_allowed=True,
        sublicense_passthrough_rate_bp=800,
        underreport_tolerance_bp=1000,
        inventor_shares=[{"inventor_name": "Ada", "share_bp": 6000},
                         {"inventor_name": "Alan", "share_bp": 4000}],
    )
    create_approved_grant(agreement, licensee, sublicensee_name="SubCo", territory="EU")

    report = submit_report(
        agreement, licensee,
        lines=[
            make_report_line(product_label="P1", units_sold=100,
                             gross_sales_cents=250_000, deductions_cents=50_000,
                             is_sublicense_revenue=False),
            make_report_line(product_label="S1", units_sold=50,
                             gross_sales_cents=100_000, deductions_cents=0,
                             is_sublicense_revenue=True),
        ],
    )
    assert report["royalty_base_cents"] == 200_000
    assert report["sublicense_net_sales_cents"] == 100_000
    # product: round(200000 * 500/10000) = 10000; passthrough: round(100000 * 800/10000) = 8000
    assert report["provisional_royalty_cents"] == 18_000

    validate_report(report["id"], benchmark_net_sales_cents=0)
    accepted = accept_report(report["id"])
    # FINAL: max(18000, 20000) = 20000 — the floor binds.
    assert accepted["final_royalty_cents"] == 20_000


def test_royalty_due_gross_sales_branch_ignores_deductions(api, analyst_headers):
    """PRD section 3.2: "`GROSS_SALES` — the base is the sum of gross sales
    over those same lines, ignoring deductions." PRD section 3.6: "the product
    component is `royalty_base_cents` multiplied by the effective rate ...
    over ten thousand, rounded half-up".

    Design: Difficulty/combinatorial_formula/royalty_due_multi_input_branch
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-30301-B2",
        royalty_base_definition="GROSS_SALES",
        base_rate_bp=500,
        underreport_tolerance_bp=1000,
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=250_000, deductions_cents=50_000)],
    )
    # GROSS_SALES base ignores deductions.
    assert report["royalty_base_cents"] == 250_000
    assert report["provisional_royalty_cents"] == 12_500


def test_minimum_floor_equality_no_double_count(api, analyst_headers):
    """PRD section 3.6: "`final_royalty_cents` is the greater of that sum and
    the agreement's `minimum_period_royalty_cents`." PRD section 2.5: "every
    threshold comparison in the system is inclusive-pass on equality unless
    explicitly stated otherwise." When the computed royalty ties the floor,
    the balance accrues the amount once.

    Design: Corner/calculations/minimum_floor_equality_no_double_count
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-33334-D2",
        minimum_period_royalty_cents=10_000,
        underreport_tolerance_bp=1000,
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=200_000)],
    )
    validate_report(report["id"], benchmark_net_sales_cents=0)
    accepted = accept_report(report["id"])
    # computed = 200000 * 5% = 10000, ties the floor exactly.
    assert accepted["final_royalty_cents"] == 10_000

    licensee_after = get_licensee(licensee["id"])
    assert licensee_after["outstanding_balance_cents"] == 10_000


def test_screening_threshold_exact_equality_passes(api, analyst_headers):
    """PRD section 3.6: "The screening threshold is the benchmark multiplied
    by ten thousand minus the agreement's `underreport_tolerance_bp`, divided
    by ten thousand, rounded half-up to a whole cent. If the report's
    `reported_net_sales_cents` is at least the threshold — equality passes —
    the report advances to `VALIDATED`; if it falls strictly below, the report
    is marked `FLAGGED`."

    Design: Difficulty/boundary_precision_check/screening_threshold_exact_equality
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-22222-K1", underreport_tolerance_bp=1000
    )
    report = submit_report(
        agreement, licensee,
        period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=180_000)],
    )
    validated = validate_report(report["id"], benchmark_net_sales_cents=200_000)
    # threshold = round(200000 * 9000/10000) = 180000; reported == threshold passes.
    assert validated["status"] == "VALIDATED"
    assert validated["benchmark_net_sales_cents"] == 200_000


def test_screening_threshold_one_cent_below_flags(api, analyst_headers):
    """PRD section 3.6: "If the report's `reported_net_sales_cents` is at
    least the threshold — equality passes — the report advances to
    `VALIDATED`; if it falls strictly below, the report is marked `FLAGGED`."

    Design: Difficulty/boundary_precision_check/screening_threshold_exact_equality
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-22223-K2", underreport_tolerance_bp=1000
    )
    report = submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=179_999)],
    )
    flagged = validate_report(report["id"], benchmark_net_sales_cents=200_000)
    # 179999 < 180000 -> FLAGGED (strict below).
    assert flagged["status"] == "FLAGGED"


def test_report_validation_fork_validated_branch(api, analyst_headers):
    """PRD section 3.6: "If the report's `reported_net_sales_cents` is at
    least the threshold — equality passes — the report advances to
    `VALIDATED`; if it falls strictly below, the report is marked `FLAGGED`."
    and "For a `VALIDATED` report, the analyst accepts it as filed — the
    request must not contain `adjusted_base_cents`." and "`cumulative_accepted_base_cents`
    increases by the accepted base (`adjusted_base_cents` on the adjustment
    path, `royalty_base_cents` otherwise)".

    Design: Difficulty/non_linear_state_machine/report_validation_fork
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-60600-E1", underreport_tolerance_bp=1000
    )
    r1 = submit_report(
        agreement, licensee,
        period_start="2026-01-01T00:00:00Z", period_end="2026-01-31T00:00:00Z",
        lines=[make_report_line(product_label="A", gross_sales_cents=100_000)],
    )
    r1 = validate_report(r1["id"], benchmark_net_sales_cents=0)
    assert r1["status"] == "VALIDATED"

    accepted = accept_report(r1["id"])
    assert accepted["status"] == "ACCEPTED"
    # Priced off royalty_base_cents 100000 at 500 bp.
    assert accepted["final_royalty_cents"] == 5000

    agreement_after = get_agreement(agreement["id"])
    assert agreement_after["cumulative_accepted_base_cents"] == 100_000
    licensee_after = get_licensee(licensee["id"])
    assert licensee_after["outstanding_balance_cents"] == 5000


def test_report_validation_fork_flagged_branch(api, analyst_headers):
    """PRD section 3.6: "For a `FLAGGED` report, the analyst accepts with
    adjustment, and `adjusted_base_cents` is mandatory; adjustments are upward
    only, so the adjusted base must be strictly greater than the report's
    `royalty_base_cents`" and "the same two rounded components as the
    provisional calculation — but with `adjusted_base_cents` standing in for
    `royalty_base_cents` on the adjustment path" and "`cumulative_accepted_base_cents`
    increases by the accepted base (`adjusted_base_cents` on the adjustment
    path, `royalty_base_cents` otherwise)".

    Design: Difficulty/non_linear_state_machine/report_validation_fork
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-60601-E2", underreport_tolerance_bp=1000
    )
    r2 = submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-02-28T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=50_000)],
    )
    r2 = validate_report(r2["id"], benchmark_net_sales_cents=200_000)
    assert r2["status"] == "FLAGGED"

    accepted = accept_report(r2["id"], {"adjusted_base_cents": 120_000})
    assert accepted["status"] == "ACCEPTED_WITH_ADJUSTMENT"
    assert accepted["adjusted_base_cents"] == 120_000
    # Priced off adjusted base 120000 at 500 bp.
    assert accepted["final_royalty_cents"] == 6000

    agreement_after = get_agreement(agreement["id"])
    assert agreement_after["cumulative_accepted_base_cents"] == 120_000


def test_immediate_visibility_after_acceptance(api, analyst_headers):
    """PRD section 2.9: "All postings happen immediately, as part of the
    triggering operation, in integer cents." PRD section 3.6: "Hop 1 posts to
    the agreement: `cumulative_accepted_base_cents` increases by the accepted
    base ... while `cumulative_recognized_revenue_cents` and
    `undistributed_pool_cents` each increase by `final_royalty_cents`."

    Design: Corner/consistency_model/immediate_visibility_after_acceptance
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-44453-X2", underreport_tolerance_bp=1000
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=100_000)],
    )
    validate_report(report["id"], benchmark_net_sales_cents=0)
    accepted = accept_report(report["id"])
    assert accepted["final_royalty_cents"] == 5000

    after = get_agreement(agreement["id"])
    assert after["cumulative_accepted_base_cents"] == 100_000
    assert after["cumulative_recognized_revenue_cents"] == 5000
    assert after["undistributed_pool_cents"] == 5000


def test_report_period_half_open_adjacency_allowed(api, analyst_headers):
    """PRD section 3.6: "The submitted window is treated as half-open —
    inclusive at `period_start`, exclusive at `period_end` — and must not
    overlap any existing report of the same agreement in `SUBMITTED`,
    `VALIDATED`, `FLAGGED`, `ACCEPTED`, `ACCEPTED_WITH_ADJUSTMENT`, or
    `AUDIT_REFERRED` status. Two periods that merely touch, one's start equal
    to the other's end, do not overlap."

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-66666-P1", underreport_tolerance_bp=1000
    )
    r1 = submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
        lines=[make_report_line(gross_sales_cents=10_000)],
    )
    # Adjacent: start == prior end. Allowed under half-open semantics.
    r2 = submit_report(
        agreement, licensee,
        period_start="2026-03-01T00:00:00Z", period_end="2026-04-01T00:00:00Z",
        lines=[make_report_line(product_label="B", gross_sales_cents=10_000)],
    )
    assert r2["status"] == "SUBMITTED"


def test_report_period_straddle_rejected(api, analyst_headers):
    """PRD section 3.6: "The submitted window is treated as half-open —
    inclusive at `period_start`, exclusive at `period_end` — and must not
    overlap any existing report of the same agreement in `SUBMITTED`,
    `VALIDATED`, `FLAGGED`, `ACCEPTED`, `ACCEPTED_WITH_ADJUSTMENT`, or
    `AUDIT_REFERRED` status. ... A colliding submission is rejected with
    `ERR_REPORT_PERIOD_OVERLAP` (HTTP 409)."

    Design: Difficulty/resource_temporal_overlap/report_period_half_open_adjacency
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-66667-P2", underreport_tolerance_bp=1000
    )
    submit_report(
        agreement, licensee,
        period_start="2026-02-01T00:00:00Z", period_end="2026-03-01T00:00:00Z",
        lines=[make_report_line(gross_sales_cents=10_000)],
    )
    payload = create_royalty_report_payload(
        agreement["id"], licensee["id"],
        period_start="2026-02-15T00:00:00Z", period_end="2026-03-15T00:00:00Z",
        lines=[make_report_line(product_label="C", gross_sales_cents=10_000)],
    )
    resp = api.create_royalty_report(payload, make_licensee_headers(licensee["id"]))
    validate_error(resp, ApiErrorId.ERR_REPORT_PERIOD_OVERLAP)


def test_validate_accepted_report_rejected(api, analyst_headers):
    """PRD section 3.6: "Either way the benchmark is stored and the report's
    `version` increments; attempting to validate a report in any other state
    is rejected with `ERR_REPORT_INVALID_STATE`."

    Design: Corner/state_machines/validate_accepted_report_rejected
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-34343-V1", underreport_tolerance_bp=1000
    )
    report = create_accepted_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=100_000)],
    )
    assert report["status"] == "ACCEPTED"
    resp = api.validate_report(
        report["id"], {"benchmark_net_sales_cents": 0}, analyst_headers
    )
    validate_error(resp, ApiErrorId.ERR_REPORT_INVALID_STATE)


def test_adjusted_base_forbidden_on_validated_accept(api, analyst_headers):
    """PRD section 2.8 tier 5: "on report acceptance `adjusted_base_cents` is
    required if and only if the report is `FLAGGED` and forbidden when the
    report is `VALIDATED`. Failures yield `ERR_VALIDATION` (HTTP 400)."

    Design: Corner/validations/adjusted_base_forbidden_on_validated_accept
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-12131-L2", underreport_tolerance_bp=1000
    )
    report = create_validated_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=10_000)],
    )
    assert report["status"] == "VALIDATED"
    resp = api.accept_report(report["id"], {"adjusted_base_cents": 99_999}, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_VALIDATION)


def test_adjustment_not_upward_rejected(api, analyst_headers):
    """PRD section 3.6: "adjustments are upward only, so the adjusted base
    must be strictly greater than the report's `royalty_base_cents`, with
    violations rejected as `ERR_ADJUSTMENT_NOT_UPWARD` (HTTP 422)."

    Design: Corner/validations/adjustment_not_upward
    """
    licensee, agreement = create_active_agreement(
        patent_reference="US-66667-G2", underreport_tolerance_bp=1000
    )
    report = submit_report(
        agreement, licensee,
        lines=[make_report_line(gross_sales_cents=50_000)],
    )
    flagged = validate_report(report["id"], benchmark_net_sales_cents=200_000)
    assert flagged["status"] == "FLAGGED"

    resp = api.accept_report(report["id"], {"adjusted_base_cents": 40_000}, analyst_headers)
    validate_error(resp, ApiErrorId.ERR_ADJUSTMENT_NOT_UPWARD)
