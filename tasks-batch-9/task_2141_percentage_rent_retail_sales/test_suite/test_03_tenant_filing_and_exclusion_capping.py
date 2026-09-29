"""Tenant filing: the per-code caps, the absolute ceilings and the aggregate
waterfall that decide how much of a claimed exclusion survives.
"""
from test_helpers import (
    TEST_DEFAULTS, ApiErrorId, assert_exclusion, assert_instant_equals,
    assert_report_net_arithmetic, assert_sales_report, exclusion_line,
    exclusions_for, make_tenant_headers, read_report, submit_report,
    submit_sales_report_payload, setup_year_with_pending_reports,
    validate_error, validate_success,
)

WATERFALL_CLAIMS = [
    exclusion_line("RETURNS_AND_ALLOWANCES", 3_000_000),
    exclusion_line("GIFT_CARD_ISSUANCE", 600_000),
    exclusion_line("EMPLOYEE_DISCOUNT", 300_000),
]


def _standard_profile_report():
    scene = setup_year_with_pending_reports(
        1, suite_code="101", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"])
    scene["report"] = scene["reports"][0]
    return scene


def test_exclusion_waterfall_trims_the_largest_line_to_the_aggregate_cap(api):
    """PRD §3.4: "The percentage cap for a line is the report's
    `gross_sales_cents` multiplied by that basis-point figure and divided by
    10000, floored to whole cents."
    PRD §3.4: "Step two applies an aggregate ceiling across all lines together.
    Total exclusions on a report may not exceed 1500 basis points — fifteen
    percent — of `gross_sales_cents`, computed as `gross_sales_cents`
    multiplied by 1500 divided by 10000 and floored to whole cents."
    PRD §3.4: "The report's `allowed_exclusions_cents` is the sum of every
    line's final `allowed_cents`, and its `net_sales_cents` is
    `gross_sales_cents` less `allowed_exclusions_cents`."

    Design: Difficulty/combinatorial_formula/exclusion_cap_waterfall_nonlinear_mode_a
    """
    scene = _standard_profile_report()

    data = validate_success(
        api.submit_sales_report(
            scene["report"]["id"],
            submit_sales_report_payload(20_000_000, WATERFALL_CLAIMS),
            make_tenant_headers(scene["tenant"]["id"])))

    assert_sales_report(data)
    assert data["status"] == "SUBMITTED"
    assert data["allowed_exclusions_cents"] == 3_000_000, (
        "the fifteen-percent aggregate cap binds the 3,150,000 of per-line "
        "allowances down to 3,000,000")
    assert data["net_sales_cents"] == 17_000_000
    assert_report_net_arithmetic(data)


def test_exclusion_waterfall_reduces_lines_in_descending_allowance_order(api):
    """PRD §3.4: "If the sum of the per-line allowances from step one exceeds
    that aggregate cap, the excess is trimmed by a waterfall and **not**
    pro-rated: the lines are taken in descending order of their step-one
    `allowed_cents`, ties broken by `created_at` oldest first, and each line in
    turn surrenders the smaller of its own `allowed_cents` and the amount of
    overage still outstanding, until the overage reaches zero."
    PRD §3.4: "Step three settles the line statuses and the report totals. A
    line whose final `allowed_cents` equals its `claimed_cents` moves `CLAIMED
    → ALLOWED`; a line whose final `allowed_cents` is zero while its
    `claimed_cents` is greater than zero moves `CLAIMED → DISALLOWED`; a line
    whose final `allowed_cents` is greater than zero but less than its
    `claimed_cents` moves `CLAIMED → PARTIALLY_ALLOWED`."

    Design: Difficulty/combinatorial_formula/exclusion_cap_waterfall_nonlinear_mode_a
    """
    scene = _standard_profile_report()
    submit_report(scene["report"]["id"], scene["tenant"]["id"], 20_000_000,
                  WATERFALL_CLAIMS)

    lines = exclusions_for(scene["report"]["id"])
    assert len(lines) == 3
    by_code = {line["code"]: line for line in lines}
    for line in lines:
        assert_exclusion(line)
        assert line["sales_report_id"] == scene["report"]["id"]

    returns = by_code["RETURNS_AND_ALLOWANCES"]
    assert returns["allowed_cents"] == 2_250_000, (
        "the largest line absorbs the whole 150,000 of overage")
    assert returns["status"] == "PARTIALLY_ALLOWED"

    gift_cards = by_code["GIFT_CARD_ISSUANCE"]
    assert gift_cards["allowed_cents"] == 500_000
    assert gift_cards["status"] == "PARTIALLY_ALLOWED"

    employee = by_code["EMPLOYEE_DISCOUNT"]
    assert employee["allowed_cents"] == 250_000
    assert employee["status"] == "PARTIALLY_ALLOWED"


def test_absolute_ceiling_binds_below_the_percentage_cap(api):
    """PRD §3.4: "Two categories additionally carry an absolute ceiling
    regardless of profile or gross sales: gift-card issuance may never exceed
    500000 cents — five thousand dollars — and employee discounts may never
    exceed 250000 cents, two thousand five hundred dollars. Where an absolute
    ceiling exists, the line's raw cap is the smaller of the percentage cap and
    that ceiling; where none exists, the raw cap is the percentage cap. The
    line's `allowed_cents` then becomes its `claimed_cents` limited by the raw
    cap, and never less than zero."

    Design: Corner/calculations/exclusion_hard_cap_binds_below_percentage_cap
    """
    scene = setup_year_with_pending_reports(
        1, suite_code="5201", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    report = scene["reports"][0]

    data = submit_report(report["id"], scene["tenant"]["id"], 100_000_000,
                         [exclusion_line("GIFT_CARD_ISSUANCE", 2_000_000)])

    assert data["allowed_exclusions_cents"] == 500_000, (
        "the five-percent percentage cap of 5,000,000 gives way to the "
        "500,000 absolute ceiling")
    assert data["net_sales_cents"] == 99_500_000

    lines = exclusions_for(report["id"])
    assert len(lines) == 1
    assert lines[0]["allowed_cents"] == 500_000
    assert lines[0]["status"] == "PARTIALLY_ALLOWED"


def test_zero_capped_code_under_a_restrictive_lease_is_refused(api):
    """PRD §3.4: "Because a `RESTRICTIVE` lease caps two categories at zero,
    claiming them at all is treated as a contract error rather than as a silent
    zeroing: an exclusion line whose code maps to a cap of 0 basis points under
    the lease's `exclusion_profile` and whose `claimed_cents` is greater than
    zero causes the whole submission to be refused with
    `ERR_EXCLUSION_CODE_NOT_PERMITTED`."

    Design: Corner/calculations/restrictive_profile_zero_cap_code_rejected
    """
    scene = setup_year_with_pending_reports(
        1, suite_code="5101", exclusion_profile="RESTRICTIVE",
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    report = scene["reports"][0]

    validate_error(
        api.submit_sales_report(
            report["id"],
            submit_sales_report_payload(
                20_000_000, [exclusion_line("GIFT_CARD_ISSUANCE", 100_000)]),
            make_tenant_headers(scene["tenant"]["id"])),
        ApiErrorId.ERR_EXCLUSION_CODE_NOT_PERMITTED.value, 422)

    report_now = read_report(report["id"])
    assert report_now["status"] == "PENDING"
    assert report_now["gross_sales_cents"] is None
    assert exclusions_for(report["id"]) == [], (
        "a refused submission writes no exclusion line at all")


def test_filing_without_exclusions_nets_the_gross_unchanged(api):
    """PRD §3.4: "A report with no exclusion lines at all yields
    `allowed_exclusions_cents` of 0 and `net_sales_cents` equal to
    `gross_sales_cents`."
    PRD §3.4: "Filing sets the report's `source` to `TENANT_REPORTED` and
    stamps `submitted_at` with the logical clock's current instant."

    Design: Corner/calculations/report_with_no_exclusions_nets_gross_unchanged
    """
    scene = setup_year_with_pending_reports(
        1, suite_code="5301", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    report = scene["reports"][0]

    data = validate_success(
        api.submit_sales_report(report["id"],
                                submit_sales_report_payload(7_777_777),
                                make_tenant_headers(scene["tenant"]["id"])))

    assert data["status"] == "SUBMITTED"
    assert data["source"] == "TENANT_REPORTED"
    assert_instant_equals(data["submitted_at"], "2026-09-01T00:00:00Z",
                          "submitted_at is stamped from the logical clock")
    assert data["allowed_exclusions_cents"] == 0
    assert data["net_sales_cents"] == 7_777_777
    assert exclusions_for(report["id"]) == []
