"""Derived-figure compliance for the reporting season's calculations.

Covers the late-furnishing penalty ladder and its member ledger, the input set the
applicable-large-employer aggregation reads, the affordability safe-harbor
fall-through, and the proposed-penalty recomputation with its member allocation.
"""

import pytest

from test_helpers import (
    PREPARER_2_USER_ID,
    TIER1_CENTS,
    TIER2_CENTS,
    TIER3_CENTS,
    TIER4_CENTS,
    assert_fields,
    assert_penalty_evidence,
    assert_twelve_coverage_lines,
    factories,
    fixtures,
    get_success_data,
    lines_by_month,
    make_benefits_admin_headers,
    make_compliance_officer_headers,
    make_preparer_headers,
    validate_paginated,
    validate_success,
)

CO = make_compliance_officer_headers()
BA = make_benefits_admin_headers()
PREPARER = make_preparer_headers()
PREPARER_2 = make_preparer_headers(PREPARER_2_USER_ID)


# ---------------------------------------------------------------------------
# Composite setups built from test_helpers.fixtures
# ---------------------------------------------------------------------------
def _two_member_determined_group(api):
    """A season whose group holds two ACTIVE members: member A at 40 full-time
    employees plus 1200 part-time hours, member B at 15 plus 600, for all twelve
    prior-year months, then an aggregated determination."""
    season = fixtures.create_filing_season(api, CO)
    group = fixtures.create_controlled_group(api, season["id"], CO, name="Bayside Group")
    member_a = fixtures.create_group_member(
        api,
        group["id"],
        "555555551",
        headers=CO,
        legal_name="Bayside Main",
        ownership_pct=80,
        measurement_method="MONTHLY",
    )
    member_b = fixtures.create_group_member(
        api,
        group["id"],
        "555555552",
        headers=CO,
        legal_name="Bayside Annex",
        ownership_pct=20,
        measurement_method="MONTHLY",
    )
    fixtures.record_headcounts(
        api,
        member_a["id"],
        headers=CO,
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    fixtures.record_headcounts(
        api,
        member_b["id"],
        headers=CO,
        full_time_employee_count=15,
        part_time_hours_total=600,
        total_employee_count=25,
    )
    determined = fixtures.run_ale_determination(api, group["id"], CO)
    return {
        "season": season,
        "group": group,
        "member_a": member_a,
        "member_b": member_b,
        "determined": determined,
    }


def _deactivate_reopen_and_redetermine(api, group_id, member_id):
    """Flip one member to INACTIVE, reopen the group and run the aggregated
    determination again over the same headcount rows."""
    get_success_data(api.update_group_member(member_id, {"member_status": "INACTIVE"}, CO))
    get_success_data(
        api.reopen_controlled_group(
            group_id, CO, {"reason": "member A left the controlled group mid-audit"}
        )
    )
    return fixtures.run_ale_determination(api, group_id, CO)


def _salaried_employee(api, group_member_id, full_name, monthly_salary_cents,
                       w2_box1_wages_cents):
    """Hire a salaried employee; the hourly rate field is left out of the body
    entirely because the rate-of-pay harbor reads the monthly salary instead."""
    payload = factories.employee_payload(
        group_member_id,
        full_name,
        ssn_last4="7788",
        is_hourly=False,
        monthly_salary_cents=monthly_salary_cents,
        w2_box1_wages_cents=w2_box1_wages_cents,
    )
    payload.pop("hourly_rate_cents", None)
    return get_success_data(api.create_employee(payload, BA))


def _employee_without_wage_harbor_data(api):
    """The shared prelude plus one MONTHLY employee whose W-2 wages and monthly
    salary are both 0, twelve 160-hour reporting-year months, and one family
    minimum-value offer covering the whole year."""
    ctx = fixtures.determined_ale_group(api)
    employee = _salaried_employee(
        api,
        ctx["member"]["id"],
        "Priya Nair",
        monthly_salary_cents=0,
        w2_box1_wages_cents=0,
    )
    fixtures.record_hours(api, employee["id"], 2026, hours_of_service=160)
    fixtures.create_coverage_offer(
        api,
        employee["id"],
        offer_kind="MEC_MV_FAMILY",
        minimum_value=True,
        lowest_cost_self_only_cents=11000,
    )
    get_success_data(api.recompute_employee_full_time(employee["id"], BA))
    ctx["employee"] = employee
    return ctx


def _furnished_electronically_at_tier_one(api):
    """The prelude plus one employee holding a GRANTED consent whose statement is
    delivered electronically thirteen days past the furnishing deadline."""
    ctx = fixtures.determined_ale_group_with_employee(
        api, employee_overrides={"full_name": "Lena Ortiz"}
    )
    employee = ctx["employee"]
    consent = fixtures.granted_consent(api, employee["id"])
    form = fixtures.generate_form(api, employee["id"], PREPARER, plan_start_month=1)
    fixtures.set_clock(api, "2027-03-15T09:00:00Z", PREPARER)
    fixtures.furnish_form(api, form["id"], "ELECTRONIC", PREPARER_2)
    ctx["consent"] = consent
    ctx["form"] = form
    return ctx


def _duplicate_mec_evidence_world(api):
    """A determined group of two ACTIVE members with both prior-year and
    reporting-year headcounts, a proposed-penalty notice asserting months 1 and 2
    plus three employee-months, and two minimum-essential-coverage proofs filed
    for the very same month 1."""
    season = fixtures.create_filing_season(api, CO)
    group = fixtures.create_controlled_group(api, season["id"], CO, name="Ironwood Group")
    member_a = fixtures.create_group_member(
        api,
        group["id"],
        "777777771",
        headers=CO,
        legal_name="Ironwood Main",
        ownership_pct=70,
        measurement_method="MONTHLY",
    )
    member_b = fixtures.create_group_member(
        api,
        group["id"],
        "777777772",
        headers=CO,
        legal_name="Ironwood Annex",
        ownership_pct=30,
        measurement_method="MONTHLY",
    )
    fixtures.record_headcounts(
        api,
        member_a["id"],
        headers=CO,
        count_year="PRIOR_YEAR",
        full_time_employee_count=40,
        part_time_hours_total=1200,
        total_employee_count=60,
    )
    fixtures.record_headcounts(
        api,
        member_b["id"],
        headers=CO,
        count_year="PRIOR_YEAR",
        full_time_employee_count=20,
        part_time_hours_total=0,
        total_employee_count=22,
    )
    fixtures.record_headcounts(
        api,
        member_a["id"],
        headers=CO,
        count_year="REPORTING_YEAR",
        full_time_employee_count=30,
        part_time_hours_total=0,
        total_employee_count=34,
    )
    fixtures.record_headcounts(
        api,
        member_b["id"],
        headers=CO,
        count_year="REPORTING_YEAR",
        full_time_employee_count=11,
        part_time_hours_total=0,
        total_employee_count=12,
    )
    fixtures.run_ale_determination(api, group["id"], CO)
    employee = fixtures.create_employee(api, member_a["id"], "Owen Pratt", BA, ssn_last4="3003")
    notice = fixtures.create_penalty_notice(
        api,
        group["id"],
        "226J-2026-0021",
        asserted_a_months=[1, 2],
        asserted_b_employee_months=[
            factories.asserted_b_pair(employee["id"], 3),
            factories.asserted_b_pair(employee["id"], 4),
            factories.asserted_b_pair(employee["id"], 5),
        ],
        headers=CO,
    )
    first_proof = fixtures.file_evidence(
        api, notice["id"], "MEC_OFFER_PROOF", 1, CO, document_ref="DOC-MEC-M1-A"
    )
    second_proof = fixtures.file_evidence(
        api, notice["id"], "MEC_OFFER_PROOF", 1, CO, document_ref="DOC-MEC-M1-B"
    )
    return {
        "season": season,
        "group": group,
        "member_a": member_a,
        "member_b": member_b,
        "employee": employee,
        "notice": notice,
        "first_proof": first_proof,
        "second_proof": second_proof,
    }


# ---------------------------------------------------------------------------
# Late-furnishing penalty tiers
# ---------------------------------------------------------------------------
PENALTY_BANDS = [
    pytest.param("2027-03-02T09:00:00Z", False, 0, id="on_the_deadline_date"),
    pytest.param("2027-03-15T09:00:00Z", False, TIER1_CENTS, id="thirteen_days_late"),
    pytest.param("2027-04-15T09:00:00Z", False, TIER2_CENTS, id="past_thirty_days_before_cutoff"),
    pytest.param("2027-08-05T09:00:00Z", False, TIER3_CENTS, id="on_or_after_cutoff"),
    pytest.param("2027-03-15T09:00:00Z", True, TIER4_CENTS, id="intentional_disregard_override"),
]


@pytest.mark.parametrize("furnish_instant,intentional_disregard,expected_penalty", PENALTY_BANDS)
def test_late_furnishing_penalty_band(api, furnish_instant, intentional_disregard,
                                      expected_penalty):
    """PRD §3.7: "The day count is the whole-day difference between the logical
    clock's UTC date and the season's `furnishing_deadline_date`."
    PRD §3.7: "A statement delivered on or before the deadline date carries no
    penalty at all — the deadline date itself is not late."
    PRD §3.7: "From one through thirty days late the penalty is 6,000 cents."
    PRD §3.7: "Beyond thirty days, a delivery whose date is still strictly before
    the season's `tier2_cutoff_date` costs 12,000 cents, and a delivery on or
    after that cutoff date costs 31,000 cents."
    PRD §3.7: "`intentional_disregard` overrides the entire tier lookup with a
    flat 63,000 cents, even for a statement that is only one day late."
    PRD §3.7: "The figure lands in the statement's `late_furnishing_penalty_cents`,
    and the member's `furnishing_penalty_total_cents` absorbs only the **delta** —
    the newly computed penalty minus whatever this statement had previously
    contributed — so a redelivery at a worse tier adds only the increase rather
    than double-counting the original charge."

    Design: Corner/Calculations/late_furnishing_penalty_tiers_across_all_four_bands
    """
    ctx = fixtures.determined_ale_group_with_employee(
        api, employee_overrides={"full_name": "Ana Reyes", "ssn_last4": "1001"}
    )
    form = fixtures.generate_form(api, ctx["employee"]["id"], PREPARER, plan_start_month=1)

    fixtures.set_clock(api, furnish_instant, PREPARER)
    furnish_overrides = {"intentional_disregard": True} if intentional_disregard else {}
    fixtures.furnish_form(api, form["id"], "PAPER", PREPARER_2, **furnish_overrides)

    delivered = fixtures.read_form(api, form["id"], PREPARER)
    assert delivered["late_furnishing_penalty_cents"] == expected_penalty, (
        f"expected {expected_penalty} cents for a delivery at {furnish_instant} "
        f"(intentional_disregard={intentional_disregard}), got "
        f"{delivered['late_furnishing_penalty_cents']}"
    )
    assert_fields(
        delivered,
        furnishing_status="FURNISHED_PAPER",
        furnished_by_user_id=PREPARER_2_USER_ID,
    )

    member = fixtures.read_member(api, ctx["member"]["id"], CO)
    assert member["furnishing_penalty_total_cents"] == expected_penalty, (
        f"the member ledger should carry the statement's only charge "
        f"{expected_penalty}, got {member['furnishing_penalty_total_cents']}"
    )


def test_member_ledger_sums_every_statements_furnishing_penalty(api):
    """PRD §3.7: "The figure lands in the statement's `late_furnishing_penalty_cents`,
    and the member's `furnishing_penalty_total_cents` absorbs only the **delta** —
    the newly computed penalty minus whatever this statement had previously
    contributed — so a redelivery at a worse tier adds only the increase rather
    than double-counting the original charge."
    PRD §3.7: "From one through thirty days late the penalty is 6,000 cents."
    PRD §3.7: "Beyond thirty days, a delivery whose date is still strictly before
    the season's `tier2_cutoff_date` costs 12,000 cents, and a delivery on or
    after that cutoff date costs 31,000 cents."
    PRD §3.7: "`intentional_disregard` overrides the entire tier lookup with a
    flat 63,000 cents, even for a statement that is only one day late."

    Design: Corner/Calculations/late_furnishing_penalty_tiers_across_all_four_bands
    """
    ctx = fixtures.determined_ale_group(api)
    member_id = ctx["member"]["id"]

    names = ["Ana Reyes", "Ben Cho", "Cara Dunn", "Dev Iyer", "Eli Nowak"]
    forms = []
    for index, name in enumerate(names, start=1):
        employee = fixtures.create_employee(
            api, member_id, name, BA, ssn_last4=f"100{index}"
        )
        forms.append(fixtures.generate_form(api, employee["id"], PREPARER, plan_start_month=1))

    # One statement per band, delivered in ascending clock order.
    fixtures.set_clock(api, "2027-03-02T09:00:00Z", PREPARER)
    fixtures.furnish_form(api, forms[0]["id"], "PAPER", PREPARER_2)
    fixtures.set_clock(api, "2027-03-15T09:00:00Z", PREPARER)
    fixtures.furnish_form(api, forms[1]["id"], "PAPER", PREPARER_2)
    fixtures.furnish_form(api, forms[2]["id"], "PAPER", PREPARER_2, intentional_disregard=True)
    fixtures.set_clock(api, "2027-04-15T09:00:00Z", PREPARER)
    fixtures.furnish_form(api, forms[3]["id"], "PAPER", PREPARER_2)
    fixtures.set_clock(api, "2027-08-05T09:00:00Z", PREPARER)
    fixtures.furnish_form(api, forms[4]["id"], "PAPER", PREPARER_2)

    expected = [0, TIER1_CENTS, TIER4_CENTS, TIER2_CENTS, TIER3_CENTS]
    actual = [
        fixtures.read_form(api, form["id"], PREPARER)["late_furnishing_penalty_cents"]
        for form in forms
    ]
    assert actual == expected, f"expected per-statement penalties {expected}, got {actual}"

    member = fixtures.read_member(api, member_id, CO)
    assert member["furnishing_penalty_total_cents"] == 112000, (
        "the member ledger should sum 0 + 6000 + 63000 + 12000 + 31000, got "
        f"{member['furnishing_penalty_total_cents']}"
    )


# ---------------------------------------------------------------------------
# The aggregation input set
# ---------------------------------------------------------------------------
def test_aggregated_determination_counts_only_active_members(api):
    """PRD §3.1: "Deactivating a member removes it from every aggregate input set
    — it stops being counted in the determination, stops receiving penalty
    allocations and stops being examined when the season is checked for
    lockability."
    PRD §3.2: "Under the aggregated basis the counted set is every `ACTIVE`
    member of the group; under the single-member basis it is exactly the named
    member."
    PRD §3.2: "The count itself reads only prior-year headcounts of counted
    members — reporting-year rows and inactive members are never read here — and
    the **rounding order is pinned**."
    PRD §3.2: "When `annual_average_fte` is below 50, the group becomes
    `DETERMINED_NON_ALE` with `ale_reason` of `BELOW_THRESHOLD` and
    `seasonal_exception_applied` false."

    Design: Corner/Calculations/inactive_group_member_excluded_from_fte_aggregation
    """
    ctx = _two_member_determined_group(api)
    before = fixtures.read_group(api, ctx["group"]["id"], CO)
    assert before["annual_average_fte"] == 70, (
        "member A at 50.00 plus member B at 20.00 should aggregate to 70, got "
        f"{before['annual_average_fte']}"
    )
    assert before["monthly_group_fte"] == [70] * 12, (
        f"expected twelve monthly figures of 70, got {before['monthly_group_fte']}"
    )
    assert_fields(before, determination_state="DETERMINED_ALE", ale_reason="THRESHOLD_MET")

    _deactivate_reopen_and_redetermine(api, ctx["group"]["id"], ctx["member_a"]["id"])

    after = fixtures.read_group(api, ctx["group"]["id"], CO)
    assert after["annual_average_fte"] == 20, (
        "with member A INACTIVE only member B's 20.00 should be counted, got "
        f"{after['annual_average_fte']}"
    )
    assert after["annual_average_fte_raw"] == pytest.approx(20.00, abs=0.01), (
        f"expected an unrounded annual average of 20.00, got {after['annual_average_fte_raw']}"
    )
    assert_fields(
        after,
        determination_state="DETERMINED_NON_ALE",
        ale_reason="BELOW_THRESHOLD",
        seasonal_exception_applied=False,
    )


def test_inactive_member_headcount_rows_are_filtered_not_deleted(api):
    """PRD §3.2: "The count itself reads only prior-year headcounts of counted
    members — reporting-year rows and inactive members are never read here — and
    the **rounding order is pinned**."
    PRD §3.1: "Each created row freezes its own `member_fte` at creation: the
    month's `full_time_employee_count` plus the month's `part_time_hours_total`
    divided by 120 hours and rounded half up to two decimal places."
    PRD §3.1: "None of these rows is ever updated afterwards; they carry no
    `version`."

    Design: Corner/Calculations/inactive_group_member_excluded_from_fte_aggregation
    """
    ctx = _two_member_determined_group(api)
    _deactivate_reopen_and_redetermine(api, ctx["group"]["id"], ctx["member_a"]["id"])

    rows, meta = validate_paginated(
        api.list_monthly_headcounts(
            CO, params={"group_member_id": ctx["member_a"]["id"], "limit": 100}
        )
    )
    assert meta["total_count"] == 12, (
        f"the deactivated member's twelve headcount rows should survive, got "
        f"{meta['total_count']}"
    )
    for row in rows:
        assert row["member_fte"] == pytest.approx(50.00, abs=0.01), (
            f"month {row['month']} should keep its frozen member_fte of 50.00, got "
            f"{row['member_fte']}"
        )

    assert_fields(fixtures.read_member(api, ctx["member_a"]["id"], CO), member_status="INACTIVE")
    assert_fields(fixtures.read_member(api, ctx["member_b"]["id"], CO), member_status="ACTIVE")


# ---------------------------------------------------------------------------
# Safe-harbor fall-through
# ---------------------------------------------------------------------------
def test_fpl_harbor_applies_when_w2_and_rate_of_pay_have_no_data(api):
    """PRD §3.6: "The W-2 harbor has data only when `w2_box1_wages_cents` is
    above 0 and `offered_month_count` is above 0; the rate-of-pay harbor has data
    only when the employee is hourly with `hourly_rate_cents` above 0, or salaried
    with `monthly_salary_cents` above 0; the federal-poverty-line harbor always
    has data."
    PRD §3.6: "Selection begins at the statement's `safe_harbor_preference` and
    then falls through the remaining harbors in the pinned order W-2, then rate of
    pay, then federal poverty line, skipping any harbor whose data is missing; a
    preference of `NONE` selects `NONE` outright with no threshold at all."
    PRD §3.6: "The federal-poverty-line threshold is `mainland_fpl_annual_cents`
    multiplied by `affordability_pct` and divided by 12, and it is the same flat
    monthly figure for every employee — it is also the figure the `1A` test in
    step C compares against."
    PRD §3.6: "The chosen harbor is recorded per month as `safe_harbor_applied`
    and the figure it produced as `affordability_threshold_cents`, which is null
    when no harbor applied."

    Design: Corner/Calculations/fpl_fall_through_when_w2_and_rate_data_missing
    """
    ctx = _employee_without_wage_harbor_data(api)
    form = fixtures.generate_form(
        api, ctx["employee"]["id"], PREPARER, plan_start_month=1, safe_harbor_preference="W2"
    )

    lines = fixtures.coverage_lines_for(api, form["id"], PREPARER)
    assert_twelve_coverage_lines(lines)
    for line in lines:
        assert line["safe_harbor_applied"] == "FPL", (
            f"month {line['month']} should fall through to FPL, got "
            f"{line['safe_harbor_applied']}"
        )
        assert line["affordability_threshold_cents"] == 11726, (
            f"month {line['month']} should carry the flat federal-poverty-line "
            f"threshold 11726, got {line['affordability_threshold_cents']}"
        )

    assert_fields(fixtures.read_form(api, form["id"], PREPARER), safe_harbor_preference="W2")


def test_fpl_threshold_drives_line14_and_line16_codes(api):
    """PRD §3.6: "Otherwise an offer of kind `MEC_MV_FAMILY` whose
    `lowest_cost_self_only_cents` is at most the federal-poverty-line threshold
    described below is `1A`."
    PRD §3.6: "`line15_amount_cents` is the offer's `lowest_cost_self_only_cents`
    when the month's `line14_code` is `1B`, `1C`, `1D`, `1E` or `1K`, and null for
    every other code."
    PRD §3.6: "A month is affordable exactly when the governing offer's
    `lowest_cost_self_only_cents` is at most that threshold; a month with no
    covering offer is never affordable, and when the applied harbor is `NONE` no
    month is affordable."
    PRD §3.6: "Otherwise an affordable month is `2F` when the applied harbor is
    `W2`, `2G` when it is `FPL`, and `2H` when it is `RATE_OF_PAY`."
    PRD §3.6: "A month's `assessable` flag is true exactly when `full_time_flag`
    is true and `line16_code` is null."

    Design: Corner/Calculations/fpl_fall_through_when_w2_and_rate_data_missing
    """
    ctx = _employee_without_wage_harbor_data(api)
    form = fixtures.generate_form(
        api, ctx["employee"]["id"], PREPARER, plan_start_month=1, safe_harbor_preference="W2"
    )

    indexed = lines_by_month(fixtures.coverage_lines_for(api, form["id"], PREPARER))
    for month in range(1, 13):
        line = indexed[month]
        assert line["line14_code"] == "1A", (
            f"month {month} offers family minimum-value coverage at 11000 cents, at or "
            f"below the federal-poverty-line threshold, so line 14 should be 1A, got "
            f"{line['line14_code']}"
        )
        assert line["line15_amount_cents"] is None, (
            f"month {month} carries line 14 code 1A, so line 15 must be null, got "
            f"{line['line15_amount_cents']}"
        )
        assert line["line16_code"] == "2G", (
            f"month {month} is affordable under the FPL harbor, so line 16 should be 2G, "
            f"got {line['line16_code']}"
        )
        assert line["assessable"] is False, (
            f"month {month} has a non-null line 16 code, so it cannot be assessable"
        )

    assert_fields(
        fixtures.read_form(api, form["id"], PREPARER),
        all_12_months_code="1A",
        offered_month_count=12,
        line15_total_cents=0,
        assessable_month_count=0,
    )


def test_monthly_method_marks_every_160_hour_month_full_time(api):
    """PRD §3.5: "The input set is the employee's hours rows whose
    `measurement_year` equals the season's `tax_year`; the month is full time
    exactly when that month's `counted_hours` is at least 130, and `ft_source` for
    the month is `MONTHLY_ACTUAL`."
    PRD §3.5: "The hire month is the calendar month of `hire_date` when that date
    falls in the tax year, and 0 when it falls in an earlier year — so a person
    hired before the reporting year is employed in all twelve months."
    PRD §3.6: "`ft_month_count` counts months with `full_time_flag` true"

    Design: Corner/Calculations/fpl_fall_through_when_w2_and_rate_data_missing
    """
    ctx = _employee_without_wage_harbor_data(api)
    form = fixtures.generate_form(
        api, ctx["employee"]["id"], PREPARER, plan_start_month=1, safe_harbor_preference="W2"
    )

    employee = fixtures.read_employee(api, ctx["employee"]["id"], BA)
    assert employee["full_time_month_count"] == 12, (
        "twelve 160-hour months all clear the 130-hour monthly test, got "
        f"{employee['full_time_month_count']}"
    )
    assert employee["ft_source_by_month"] == ["MONTHLY_ACTUAL"] * 12, (
        f"expected twelve MONTHLY_ACTUAL sources, got {employee['ft_source_by_month']}"
    )
    assert_fields(fixtures.read_form(api, form["id"], PREPARER), ft_month_count=12)


# ---------------------------------------------------------------------------
# Redelivery and the penalty delta
# ---------------------------------------------------------------------------
def test_electronic_delivery_at_tier_one_charges_the_member_ledger(api):
    """PRD §3.7: "From one through thirty days late the penalty is 6,000 cents."
    PRD §3.7: "Electronic delivery additionally requires the employee to hold a
    consent at `GRANTED`, and the absence of one is refused with
    `ERR_CONSENT_NOT_GRANTED`."
    PRD §3.7: "The figure lands in the statement's `late_furnishing_penalty_cents`,
    and the member's `furnishing_penalty_total_cents` absorbs only the **delta** —
    the newly computed penalty minus whatever this statement had previously
    contributed — so a redelivery at a worse tier adds only the increase rather
    than double-counting the original charge."

    Design: Corner/Calculations/refurnish_after_redelivery_absorbs_only_penalty_delta
    """
    ctx = _furnished_electronically_at_tier_one(api)

    assert_fields(
        fixtures.read_form(api, ctx["form"]["id"], PREPARER),
        furnishing_status="FURNISHED_ELECTRONIC",
        late_furnishing_penalty_cents=TIER1_CENTS,
    )
    member = fixtures.read_member(api, ctx["member"]["id"], CO)
    assert member["furnishing_penalty_total_cents"] == TIER1_CENTS, (
        f"the ledger should carry the single tier-one charge {TIER1_CENTS}, got "
        f"{member['furnishing_penalty_total_cents']}"
    )


def test_consent_withdrawal_forces_redelivery_without_a_second_charge(api):
    """PRD §3.7: "Withdrawal is not a quiet bookkeeping change: every statement of
    that employee sitting at `FURNISHED_ELECTRONIC` is pushed back to
    `REDELIVERY_REQUIRED`, which increments the controlled group's
    `open_correction_count`, moves a `DETERMINED_ALE` group to `CORRECTION_OPEN`
    and increments the season's `open_correction_count`."
    PRD §3.7: "The figure lands in the statement's `late_furnishing_penalty_cents`,
    and the member's `furnishing_penalty_total_cents` absorbs only the **delta** —
    the newly computed penalty minus whatever this statement had previously
    contributed — so a redelivery at a worse tier adds only the increase rather
    than double-counting the original charge."

    Design: Corner/Calculations/refurnish_after_redelivery_absorbs_only_penalty_delta
    """
    ctx = _furnished_electronically_at_tier_one(api)
    fixtures.withdraw_consent(api, ctx["consent"]["id"], ctx["employee"]["id"])

    assert_fields(
        fixtures.read_form(api, ctx["form"]["id"], PREPARER),
        furnishing_status="REDELIVERY_REQUIRED",
        late_furnishing_penalty_cents=TIER1_CENTS,
    )
    member = fixtures.read_member(api, ctx["member"]["id"], CO)
    assert member["furnishing_penalty_total_cents"] == TIER1_CENTS, (
        "a status change is not a charge, so the ledger should still read "
        f"{TIER1_CENTS}, got {member['furnishing_penalty_total_cents']}"
    )


def test_redelivery_at_a_worse_tier_adds_only_the_penalty_delta(api):
    """PRD §3.7: "It is accepted only from `NOT_FURNISHED` or
    `REDELIVERY_REQUIRED`, so `furnishing_status` walks `NOT_FURNISHED` →
    `FURNISHED_PAPER` or `NOT_FURNISHED` → `FURNISHED_ELECTRONIC` on first
    delivery and `REDELIVERY_REQUIRED` → `FURNISHED_PAPER` or
    `REDELIVERY_REQUIRED` → `FURNISHED_ELECTRONIC` on redelivery."
    PRD §3.7: "Beyond thirty days, a delivery whose date is still strictly before
    the season's `tier2_cutoff_date` costs 12,000 cents, and a delivery on or
    after that cutoff date costs 31,000 cents."
    PRD §3.7: "The figure lands in the statement's `late_furnishing_penalty_cents`,
    and the member's `furnishing_penalty_total_cents` absorbs only the **delta** —
    the newly computed penalty minus whatever this statement had previously
    contributed — so a redelivery at a worse tier adds only the increase rather
    than double-counting the original charge."

    Design: Corner/Calculations/refurnish_after_redelivery_absorbs_only_penalty_delta
    """
    ctx = _furnished_electronically_at_tier_one(api)
    fixtures.withdraw_consent(api, ctx["consent"]["id"], ctx["employee"]["id"])
    fixtures.set_clock(api, "2027-04-15T09:00:00Z", PREPARER)

    redelivered = validate_success(
        api.furnish_form_1095c(
            ctx["form"]["id"], factories.furnish_payload("PAPER"), PREPARER_2
        ),
        200,
    )
    assert_fields(redelivered, furnishing_status="FURNISHED_PAPER")

    form = fixtures.read_form(api, ctx["form"]["id"], PREPARER)
    assert form["late_furnishing_penalty_cents"] == TIER2_CENTS, (
        f"the redelivery date is 44 days late and before the tier-two cutoff, so the "
        f"statement should be repriced at {TIER2_CENTS}, got "
        f"{form['late_furnishing_penalty_cents']}"
    )
    assert_fields(form, furnished_by_user_id=PREPARER_2_USER_ID)

    member = fixtures.read_member(api, ctx["member"]["id"], CO)
    assert member["furnishing_penalty_total_cents"] == TIER2_CENTS, (
        f"the ledger should absorb only the delta and read {TIER2_CENTS}, neither "
        f"18000 nor {TIER1_CENTS}, got {member['furnishing_penalty_total_cents']}"
    )


# ---------------------------------------------------------------------------
# Penalty recomputation over duplicate evidence
# ---------------------------------------------------------------------------
def test_duplicate_month_evidence_is_stored_but_not_applied(api):
    """PRD §3.9: "**Step 1 applies the evidence in `created_at` ascending order**,
    walking two working sets that begin as the asserted month list and the
    asserted employee-month pairs."
    PRD §3.9: "A `MEC_OFFER_PROOF` whose month is still in the month set removes
    that month and is marked `applied` true."
    PRD §3.9: "Evidence whose target an earlier piece already removed — two
    minimum-essential-coverage proofs for the same month, or an offer proof filed
    after a full-time dispute on the same employee-month — is left `applied` false
    and changes nothing, which is why `applied_evidence_count` can be smaller than
    `evidence_count`."
    PRD §3.9: "Recomputation moves `EVIDENCE_GATHERING` → `RECOMPUTED`, needs at
    least one piece of evidence, and needs every statement named by an
    `FT_STATUS_DISPUTE` or `OFFER_PROOF` row to have reached the agency — a filing
    dimension of `FILED_ACCEPTED`, `FILED_WITH_ERRORS` or `CORRECTION_DRAFTED` —
    or it is refused with `ERR_EVIDENCE_FORM_NOT_FILED`."

    Design: Corner/Calculations/duplicate_evidence_second_row_not_applied
    """
    ctx = _duplicate_mec_evidence_world(api)

    recomputed = validate_success(
        api.recompute_penalty_notice(ctx["notice"]["id"], CO), 200
    )
    assert_fields(recomputed, status="RECOMPUTED")

    first = get_success_data(api.get_penalty_evidence(ctx["first_proof"]["id"], CO))
    second = get_success_data(api.get_penalty_evidence(ctx["second_proof"]["id"], CO))
    assert_penalty_evidence(first, applied=True)
    assert_penalty_evidence(second, applied=False)

    notice = fixtures.read_notice(api, ctx["notice"]["id"], CO)
    assert_fields(notice, evidence_count=2, applied_evidence_count=1)


def test_only_the_uncleared_asserted_month_is_priced(api):
    """PRD §3.9: "the section (a) monthly amount is the season's
    `penalty_a_annual_cents` divided by 12 and truncated to whole cents, and the
    section (b) monthly amount is `penalty_b_annual_cents` divided by 12 and
    truncated the same way."
    PRD §3.9: "For each month the count is the sum of `full_time_employee_count`
    over the reporting-year headcount rows of the group's `ACTIVE` members, less
    the full-time reductions step 1 recorded for that month."
    PRD §3.9: "For each month still surviving in the asserted month set, the
    charge is the recomputed group full-time count for that month less the
    thirty-employee exclusion — floored at zero, so a month whose count is at or
    below thirty contributes nothing — multiplied by the section (a) monthly
    amount."
    PRD §3.9: "The two sections are mutually exclusive per month, so any surviving
    employee-month pair whose month also survives in the asserted month set is
    dropped here."
    PRD §3.9: "`recalculated_amount_cents` is the sum of the two components."

    Design: Corner/Calculations/duplicate_evidence_second_row_not_applied
    """
    ctx = _duplicate_mec_evidence_world(api)
    fixtures.recompute_notice(api, ctx["notice"]["id"], CO)

    notice = fixtures.read_notice(api, ctx["notice"]["id"], CO)
    assert notice["a_month_penalty_cents"] == 271700, (
        "only month 2 survives the evidence, at max(41 - 30, 0) times 24700, got "
        f"{notice['a_month_penalty_cents']}"
    )
    assert notice["b_month_penalty_cents"] == 111000, (
        "three surviving employee-months at 37000 each, none of them in a surviving "
        f"asserted month, got {notice['b_month_penalty_cents']}"
    )
    assert notice["recalculated_amount_cents"] == 382700, (
        f"expected 271700 + 111000, got {notice['recalculated_amount_cents']}"
    )
    assert notice["asserted_a_months"] == [1, 2], (
        "the recomputation walks a working copy, so the asserted month list must be "
        f"unchanged, got {notice['asserted_a_months']}"
    )


def test_recalculated_cents_allocate_by_reporting_year_ft_months(api):
    """PRD §3.9: "**Step 6 allocates the recalculated cents** the same way,
    writing each member's `allocated_penalty_cents`, with the whole leftover
    remainder going to the member with the largest weight."
    PRD §2.9: "Cents are distributed the same way except that the entire leftover
    remainder goes to the single member with the largest weight, ties broken by
    the earlier member `created_at`, again never by id."
    PRD §2.9: "In both cases the weight is the member's
    `reporting_year_ft_months`."
    PRD §3.9: "`allocated_total_cents` is the sum of those member allocations and
    equals `recalculated_amount_cents`, leaving `unallocated_amount_cents` at zero
    — that field is the conserved-quantity slack, and its being zero is what
    proves the allocation settled."

    Design: Corner/Calculations/duplicate_evidence_second_row_not_applied
    """
    ctx = _duplicate_mec_evidence_world(api)
    fixtures.recompute_notice(api, ctx["notice"]["id"], CO)

    member_a = fixtures.read_member(api, ctx["member_a"]["id"], CO)
    member_b = fixtures.read_member(api, ctx["member_b"]["id"], CO)
    assert member_a["reporting_year_ft_months"] == 360, (
        f"expected twelve months of 30 full-time employees, got "
        f"{member_a['reporting_year_ft_months']}"
    )
    assert member_b["reporting_year_ft_months"] == 132, (
        f"expected twelve months of 11 full-time employees, got "
        f"{member_b['reporting_year_ft_months']}"
    )
    assert member_a["allocated_penalty_cents"] == 280025, (
        "member A takes the floor of its weighted share plus the whole one-cent "
        f"remainder, got {member_a['allocated_penalty_cents']}"
    )
    assert member_b["allocated_penalty_cents"] == 102675, (
        f"expected member B's weighted floor of 102675, got "
        f"{member_b['allocated_penalty_cents']}"
    )

    notice = fixtures.read_notice(api, ctx["notice"]["id"], CO)
    assert notice["allocated_total_cents"] == 382700, (
        f"the allocations must sum to the recalculated amount, got "
        f"{notice['allocated_total_cents']}"
    )
    assert notice["unallocated_amount_cents"] == 0, (
        f"a settled allocation leaves nothing unallocated, got "
        f"{notice['unallocated_amount_cents']}"
    )
