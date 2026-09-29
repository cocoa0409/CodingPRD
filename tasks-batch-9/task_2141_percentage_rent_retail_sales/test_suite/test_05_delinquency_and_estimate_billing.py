"""Estimate billing a delinquent period: the trailing-history lookback, the
no-history fallback, the version guard and the compensating void when the
tenant finally files.
"""
from test_helpers import (
    accept_report, ApiErrorId, charges_for_year,
    estimate_bill, LEASE_ADMIN, lease_year_version, ledger_entries,
    read_charge, read_lease, read_lease_year, read_report,
    schedule_monthly_report, set_clock, setup_year_with_accepted_reports,
    setup_year_with_pending_reports, submit_report, TEST_DEFAULTS,
    validate_error, validate_success,
)

ARTIFICIAL_BREAKPOINT = TEST_DEFAULTS["ARTIFICIAL_BREAKPOINT_CENTS"]


def _september_history_with_two_delinquent_periods():
    """Accepted September, then October estimate-billed, then November due."""
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="401", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    lease_year_id = scene["lease_year"]["id"]
    scene["october"] = schedule_monthly_report(lease_year_id, 2)
    scene["november"] = schedule_monthly_report(lease_year_id, 3)
    set_clock("2026-11-12T00:00:00Z")
    estimate_bill(scene["october"]["id"], lease_year_id)
    set_clock("2026-12-12T00:00:00Z")
    return scene


def test_estimate_lookback_drops_the_landlord_estimate_that_precedes_it(api):
    """PRD §3.6: "Eligible history consists of reports of the *same* reporting
    year whose `source` is `TENANT_REPORTED`, whose status is either `ACCEPTED`
    or `ADJUSTED`, and whose `period_end` is at or before the delinquent
    report's `period_start`. Reports whose `source` is `LANDLORD_ESTIMATE` are
    excluded at every depth, so a run of consecutive estimates never compounds
    on itself. That history is sorted by `period_end` newest first, ties broken
    by `created_at` newest first, and the three most recent entries form the
    window."
    PRD §3.6: "When the window contains at least one report, the base is the
    sum of `gross_sales_cents` across the window divided by the number of
    reports in the window, rounded half up to whole cents; the estimated gross
    is then that base multiplied by 11000 basis points and divided by 10000 — a
    ten percent uplift over the tenant's own trailing average, applied as a
    penalty for non-filing — rounded half up to whole cents."

    Design: Difficulty/combinatorial_formula/delinquency_estimate_lookback_excludes_prior_estimates_mode_c
    """
    scene = _september_history_with_two_delinquent_periods()

    estimate_bill(scene["november"]["id"], scene["lease_year"]["id"])

    october = read_report(scene["october"]["id"])
    assert october["gross_sales_cents"] == 33_000_000
    assert october["source"] == "LANDLORD_ESTIMATE"

    november = read_report(scene["november"]["id"])
    assert november["gross_sales_cents"] == 33_000_000, (
        "the October estimate is excluded, so the window is still the single "
        "tenant-reported 30,000,000 September period")
    assert november["net_sales_cents"] == 33_000_000
    assert november["allowed_exclusions_cents"] == 0
    assert november["status"] == "ESTIMATED"
    assert november["is_delinquent"] is True


def test_second_estimate_bills_against_the_cumulative_that_now_includes_it(api):
    """PRD §3.6: "Only then, third, does percentage-rent billing run — against
    a cumulative that now includes the estimate. The reporting year's
    `cumulative_net_sales_cents` increases by the estimate's `net_sales_cents`
    and a ledger entry of type `ESTIMATE_ISSUED` is appended with that figure
    as its `delta_net_sales_cents`."
    PRD §3.6: "Two more effects close the operation. The lease's
    `delinquency_strikes` increases by 1, and the occupancy-cost computation of
    Section 3.5 re-runs — which matters because a lease that has accumulated
    three or more strikes is forced onto `WATCHLIST` regardless of how healthy
    its occupancy-cost ratio looks."

    Design: Difficulty/combinatorial_formula/delinquency_estimate_lookback_excludes_prior_estimates_mode_c
    """
    scene = _september_history_with_two_delinquent_periods()

    estimate_bill(scene["november"]["id"], scene["lease_year"]["id"])

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 96_000_000
    assert year["cumulative_billed_cents"] == 3_360_000

    november_charges = charges_for_year(
        scene["lease_year"]["id"], sales_report_id=scene["november"]["id"])
    assert len(november_charges) == 1
    assert november_charges[0]["charge_type"] == "ESTIMATE"
    assert november_charges[0]["billing_status"] == "ISSUED"
    assert november_charges[0]["amount_cents"] == 1_980_000, (
        "the year owes 3,360,000 in total and 1,380,000 was already issued")

    assert read_lease(scene["lease"]["id"])["delinquency_strikes"] == 2


def test_estimate_billing_at_the_exact_due_instant_is_refused(api):
    """PRD §3.6: "Once the logical clock reads strictly later than a `PENDING`
    report's `due_at`, a `LeaseAdministrator` may estimate-bill the period,
    moving the report `PENDING → ESTIMATED`. Attempting this while the clock is
    at or before `due_at` is refused with `ERR_REPORT_NOT_DELINQUENT`; the
    report must genuinely be past due, not merely due."

    Design: Difficulty/boundary_precision_check/estimate_bill_at_exact_due_instant_rejected_then_one_second_later_succeeds
    """
    scene = setup_year_with_pending_reports(
        1, suite_code="1601", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    report = scene["reports"][0]
    set_clock("2026-10-11T00:00:00Z")
    version = lease_year_version(scene["lease_year"]["id"])

    validate_error(
        api.estimate_bill_sales_report(
            report["id"], {"expected_lease_year_version": version}, LEASE_ADMIN),
        ApiErrorId.ERR_REPORT_NOT_DELINQUENT.value, 409)

    assert read_report(report["id"])["status"] == "PENDING"
    assert read_lease(scene["lease"]["id"])["delinquency_strikes"] == 0


def test_estimate_one_second_past_due_falls_back_to_the_contract_breakpoint(api):
    """PRD §3.6: "When the window is empty, the tenant has no usable history,
    and the estimate instead falls back to the contract: the reporting year's
    `breakpoint_cents` divided by the number of periods in a year — twelve for
    a `MONTHLY` lease, four for a `QUARTERLY` one — multiplied by 8000 basis
    points and divided by 10000, that is eighty percent of a pro-rata share of
    the annual breakpoint, rounded half up to whole cents."
    PRD §3.6: "The resulting figure is written to the report's
    `gross_sales_cents`. An estimate carries no exclusions at all, so
    `allowed_exclusions_cents` is set to 0 and `net_sales_cents` is set equal
    to the estimated gross. The report's `source` becomes `LANDLORD_ESTIMATE`,
    which also makes its `is_delinquent` flag permanently true."

    Design: Difficulty/boundary_precision_check/estimate_bill_at_exact_due_instant_rejected_then_one_second_later_succeeds
    """
    scene = setup_year_with_pending_reports(
        1, suite_code="1601", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    report = scene["reports"][0]
    set_clock("2026-10-11T00:00:01Z")
    version = lease_year_version(scene["lease_year"]["id"])

    data = validate_success(
        api.estimate_bill_sales_report(
            report["id"], {"expected_lease_year_version": version}, LEASE_ADMIN))

    assert data["status"] == "ESTIMATED"
    assert data["source"] == "LANDLORD_ESTIMATE"
    assert data["gross_sales_cents"] == 2_666_667
    assert data["net_sales_cents"] == 2_666_667

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 2_666_667
    assert year["cumulative_billed_cents"] == 0, (
        "the estimate stays well below the 40,000,000 breakpoint")
    assert charges_for_year(scene["lease_year"]["id"]) == []
    assert read_lease(scene["lease"]["id"])["delinquency_strikes"] == 1


def test_lookback_window_keeps_only_the_three_most_recent_periods(api):
    """PRD §3.6: "That history is sorted by `period_end` newest first, ties
    broken by `created_at` newest first, and the three most recent entries form
    the window."
    PRD §3.6: "When the window contains at least one report, the base is the
    sum of `gross_sales_cents` across the window divided by the number of
    reports in the window, rounded half up to whole cents; the estimated gross
    is then that base multiplied by 11000 basis points and divided by 10000 — a
    ten percent uplift over the tenant's own trailing average, applied as a
    penalty for non-filing — rounded half up to whole cents."

    Design: Corner/calculations/estimate_lookback_uses_only_the_three_most_recent_periods
    """
    scene = setup_year_with_accepted_reports(
        [12_000_000, 24_000_000, 30_000_000, 36_000_000], suite_code="5401",
        breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=TEST_DEFAULTS["UNREACHABLE_BREAKPOINT_CENTS"])
    january = schedule_monthly_report(scene["lease_year"]["id"], 5)
    set_clock("2027-02-12T00:00:00Z")

    estimate_bill(january["id"], scene["lease_year"]["id"])

    filed = read_report(january["id"])
    assert filed["gross_sales_cents"] == 33_000_000, (
        "the average of the three most recent periods is 30,000,000, uplifted "
        "by ten percent")
    assert filed["net_sales_cents"] == 33_000_000
    assert filed["status"] == "ESTIMATED"
    assert filed["source"] == "LANDLORD_ESTIMATE"

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 135_000_000
    assert year["cumulative_billed_cents"] == 0
    assert charges_for_year(scene["lease_year"]["id"]) == []
    assert read_lease(scene["lease"]["id"])["delinquency_strikes"] == 1


def test_estimate_bill_with_a_stale_reporting_year_version_is_rejected(api):
    """PRD §2.8: "`POST /retail/sales-reports/{id}/estimate-bill` requires a
    non-optional `expected_lease_year_version` field in its request body,
    carrying the client's last observed `version` of the `LeaseYear` that owns
    the report."
    PRD §2.8: "If `expected_lease_year_version` does not equal the reporting
    year's current `version`, the request is rejected with
    `ERR_STALE_LEASE_YEAR_VERSION` (HTTP 412). A successful estimate billing
    itself advances that reporting year's `version` by 1."

    Design: Corner/cross_cutting_layers/stale_lease_year_version_on_estimate_bill_returns_412
    """
    scene = setup_year_with_pending_reports(
        2, suite_code="9101", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    september, october = scene["reports"]
    submit_report(september["id"], scene["tenant"]["id"], 30_000_000)
    stale_version = lease_year_version(scene["lease_year"]["id"])
    accept_report(september["id"])
    set_clock("2026-11-12T00:00:00Z")

    validate_error(
        api.estimate_bill_sales_report(
            october["id"], {"expected_lease_year_version": stale_version},
            LEASE_ADMIN),
        ApiErrorId.ERR_STALE_LEASE_YEAR_VERSION.value, 412)

    october_now = read_report(october["id"])
    assert october_now["status"] == "PENDING"
    assert october_now["gross_sales_cents"] is None
    assert read_lease(scene["lease"]["id"])["delinquency_strikes"] == 0
    assert charges_for_year(scene["lease_year"]["id"]) == []


def test_late_actual_voids_the_estimate_charge_and_rebills_the_real_figures(api):
    """PRD §3.4: "Third, caused by the second, every percentage-rent charge
    whose `sales_report_id` is this report, whose `charge_type` is `ESTIMATE`
    and whose `billing_status` is `ISSUED` flips to `VOID`; the year's
    `cumulative_billed_cents` decreases by that charge's `amount_cents` and a
    ledger entry of type `ESTIMATE_VOIDED` is appended carrying that amount
    negated as its `delta_billed_cents` and 0 as its `delta_net_sales_cents`."
    PRD §3.6: "An estimate is never the last word. When the tenant eventually
    files the real numbers, the `ESTIMATED → SUBMITTED` leg of Section 3.4
    withdraws the estimate from the year's cumulative sales and voids the
    `ESTIMATE` charge, and ordinary acceptance then bills the actual figures."

    Design: Difficulty/compensating_invariant/estimate_void_leaves_billed_ledger_balanced
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="2301", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    october = schedule_monthly_report(scene["lease_year"]["id"], 2)
    set_clock("2026-11-12T00:00:00Z")
    estimate_bill(october["id"], scene["lease_year"]["id"])
    estimate_charge = charges_for_year(scene["lease_year"]["id"],
                                       charge_type="ESTIMATE")[0]

    submit_report(october["id"], scene["tenant"]["id"], 28_000_000)
    accept_report(october["id"])

    october_now = read_report(october["id"])
    assert october_now["status"] == "ACCEPTED"
    assert october_now["source"] == "TENANT_REPORTED"
    assert october_now["gross_sales_cents"] == 28_000_000

    voided = read_charge(estimate_charge["id"])
    assert voided["billing_status"] == "VOID"
    assert voided["amount_cents"] == 1_380_000

    issued = charges_for_year(scene["lease_year"]["id"], billing_status="ISSUED")
    assert len(issued) == 1
    assert issued[0]["charge_type"] == "PERIODIC"
    assert issued[0]["amount_cents"] == 1_080_000

    year = read_lease_year(scene["lease_year"]["id"])
    assert year["cumulative_net_sales_cents"] == 58_000_000
    assert year["cumulative_billed_cents"] == 1_080_000


def test_estimate_and_its_reversal_leave_the_ledger_balanced(api):
    """PRD §3.4: "Second, caused by the first, the reporting year's
    `cumulative_net_sales_cents` decreases by the estimate's former
    `net_sales_cents` and a ledger entry of type `REPORT_WITHDRAWN` is appended
    carrying that figure negated as its `delta_net_sales_cents` and 0 as its
    `delta_billed_cents`."
    PRD §2.11: "Each entry carries `lease_year_id`, an `entry_type` naming
    which cascade wrote it, a signed `delta_net_sales_cents`, a signed
    `delta_billed_cents` and a free-text `note` recording the entity name and
    action that produced it."

    Design: Difficulty/compensating_invariant/estimate_void_leaves_billed_ledger_balanced
    """
    scene = setup_year_with_accepted_reports(
        [30_000_000], suite_code="2301", breakpoint_type="ARTIFICIAL",
        artificial_breakpoint_cents=ARTIFICIAL_BREAKPOINT)
    october = schedule_monthly_report(scene["lease_year"]["id"], 2)
    set_clock("2026-11-12T00:00:00Z")
    estimate_bill(october["id"], scene["lease_year"]["id"])

    submit_report(october["id"], scene["tenant"]["id"], 28_000_000)
    accept_report(october["id"])

    entries = ledger_entries(scene["lease_year"]["id"])
    net_movements = [entry["delta_net_sales_cents"] for entry in entries]
    billed_movements = [entry["delta_billed_cents"] for entry in entries]
    assert sum(net_movements) == 58_000_000, (
        f"reported sales must conserve; movements were {net_movements}")
    assert sum(billed_movements) == 1_080_000, (
        f"billed money must conserve; movements were {billed_movements}")

    types = [entry["entry_type"] for entry in entries]
    assert "REPORT_WITHDRAWN" in types
    assert "ESTIMATE_VOIDED" in types
    assert -1_380_000 in billed_movements, (
        "the voided estimate charge is reversed in the ledger")
    assert read_lease(scene["lease"]["id"])["delinquency_strikes"] == 1
