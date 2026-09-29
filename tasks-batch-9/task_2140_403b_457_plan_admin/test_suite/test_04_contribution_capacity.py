"""Contribution capacity: the two aggregation bases, catch-ups and ceilings."""

from test_helpers import (
    ApiErrorId,
    assert_limit_summary_reconciles,
    create_active_plan,
    create_plan,
    determine_eligibility,
    file_notice,
    make_officer_headers,
    open_contract,
    register_employer,
    register_nonqualified_employer,
    register_participant,
    register_second_vendor,
    register_vendor,
    report_balance,
    set_clock,
    setup_active_agreement,
    setup_plan_env,
    submit_election,
    validate_error,
    validate_paginated,
    validate_success,
)


def _dual_basis_env():
    """Two providers on one 403(b) plan: one feed fresh, one 92 days stale, with a
    fully seeded participant and a SUBMITTED election of 1,800,000 cents."""
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    env["agreement_fresh"] = setup_active_agreement(
        env["plan_id"], env["vendor_ids"][0], env["employer_id"], feed_date="2026-07-31"
    )
    env["agreement_stale"] = setup_active_agreement(
        env["plan_id"], env["vendor_ids"][1], env["employer_id"], feed_date="2026-05-01"
    )
    file_notice(env["plan_id"], env["employer_id"])
    participant = register_participant(
        env["employer_id"], date_of_birth="1968-03-15", hire_date="2006-08-01",
        years_of_service=20,
    )
    account_fresh = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
        prior_years_elective_deferrals_cents=4_000_000,
    )
    report_balance(
        account_fresh["id"], env["vendor_ids"][0], as_of_date="2026-07-31",
        accumulated_benefit_cents=5_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=1_000_000,
    )
    account_stale = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=3_000_000,
        prior_years_elective_deferrals_cents=3_000_000,
    )
    report_balance(
        account_stale["id"], env["vendor_ids"][1], as_of_date="2026-05-01",
        accumulated_benefit_cents=3_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=800_000,
    )
    determine_eligibility(env["plan_id"], participant["id"], "co-1")
    election = submit_election(
        participant["id"], env["plan_id"], account_fresh["id"], env["employer_id"],
        annual_deferral_amount_cents=1_800_000, effective_from="2026-09-01",
        effective_through="2026-12-31", catchup_election="AGE_50_AND_SERVICE_15_YEAR",
    )
    env.update(
        participant=participant, participant_id=participant["id"],
        account_fresh_id=account_fresh["id"], account_stale_id=account_stale["id"],
        election=election, election_id=election["id"],
    )
    return env


def test_deferral_room_reports_gross_and_verified_bases_side_by_side(api):
    """PRD §3.5: "`ytd_gross_cents` is the sum of `ytd_elective_deferrals_cents` over the
    included set; `ytd_verified_cents` is that same sum over the verified set only."
    PRD §3.5: "`room_gross_cents` is the total limit less `ytd_gross_cents`, floored at
    zero; `room_verified_cents` is the total limit less `ytd_verified_cents`, floored at
    zero."
    PRD §3.5: "The **gross basis** counts year-to-date deferrals on every included
    contract, including contracts whose agreement is missing, `PENDING`, `SUSPENDED` or
    `TERMINATED`, or whose feed has gone stale; it yields the smaller room and it is the
    conservative figure the plan is obliged to act on."

    Design: Difficulty/dual_variant_calc/deferral_room_gross_basis_versus_verified_basis
    """
    env = _dual_basis_env()

    summary = validate_success(
        api.get_contribution_limit_summary(
            env["participant_id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )

    assert summary["basic_limit_cents"] == 2_450_000
    assert summary["service_15yr_catchup_capacity_cents"] == 300_000
    assert summary["age50_catchup_capacity_cents"] == 800_000
    assert summary["total_limit_cents"] == 3_550_000
    assert summary["lifetime_elective_deferrals_cents"] == 8_800_000
    assert summary["ytd_gross_cents"] == 1_800_000
    assert summary["ytd_verified_cents"] == 1_000_000
    assert summary["room_gross_cents"] == 1_750_000
    assert summary["room_verified_cents"] == 2_550_000
    assert summary["room_verified_cents"] - summary["room_gross_cents"] == 800_000, (
        "the difference between the rooms is exactly the deferral total behind the "
        "stale contract"
    )
    assert_limit_summary_reconciles(summary)


def test_election_limit_enforcement_uses_the_gross_basis(api):
    """PRD §3.5: "Every rejection of an election for breaching the elective-deferral limit
    is decided on the gross basis."
    PRD §3.6: "If anything at all remains unattributed after step four, the approval is
    refused with `ERR_402G_LIMIT_EXCEEDED` and nothing is written."

    Design: Difficulty/dual_variant_calc/deferral_room_gross_basis_versus_verified_basis
    """
    env = _dual_basis_env()

    response = api.decide_election(
        env["election_id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )

    validate_error(response, ApiErrorId.ERR_402G_LIMIT_EXCEEDED.value)
    election = validate_success(api.get_election(env["election_id"], make_officer_headers()))
    assert election["state"] == "SUBMITTED", "the refused approval leaves the row untouched"
    participant = validate_success(
        api.get_participant(env["participant_id"], make_officer_headers())
    )
    assert participant["cumulative_special_catchup_used_cents"] == 0


def test_service_catchup_binds_on_the_lifetime_term_for_a_qualified_organization(api):
    """PRD §3.5: "The fifteen-year service catch-up is available only when the sponsor's
    `is_qualified_organization` is true and the participant's `years_of_service` is at
    least 15; when either condition fails, the capacity is zero. When both hold, the
    capacity is the smallest of three independently computed figures, floored at zero:
    an annual ceiling of 3,000 dollars; a lifetime ceiling of 15,000 dollars reduced by
    the participant's `cumulative_special_catchup_used_cents`; and 5,000 dollars
    multiplied by the participant's `years_of_service` rounded down to a whole number of
    years, reduced by the participant's `lifetime_elective_deferrals_cents`."
    PRD §2.10: "`lifetime_elective_deferrals_cents` is
    `prior_employer_elective_deferrals_cents` plus, over the participant's open contracts
    held under plans whose `plan_type` is `PLAN_403B`, the sum of
    `prior_years_elective_deferrals_cents` and `ytd_elective_deferrals_cents` on each
    such contract."

    Design: Difficulty/combinatorial_formula/service_15yr_catchup_three_way_min_with_qualified_org_branch
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    participant = register_participant(
        env["employer_id"], full_name="Ben Okafor", date_of_birth="1980-01-01",
        hire_date="2010-01-01", years_of_service=16,
        prior_employer_elective_deferrals_cents=500_000,
        cumulative_special_catchup_used_cents=1_350_000,
    )
    open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-B001", accumulated_benefit_cents=1_000_000,
        prior_years_elective_deferrals_cents=6_800_000,
    )

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )

    assert summary["lifetime_elective_deferrals_cents"] == 7_300_000
    assert summary["service_15yr_catchup_capacity_cents"] == 150_000, (
        "the lifetime ceiling term 1500000 - 1350000 binds, not the 300000 annual cap "
        "and not the 8000000 - 7300000 service term"
    )
    assert summary["age50_catchup_capacity_cents"] == 0
    assert summary["total_limit_cents"] == 2_600_000
    assert_limit_summary_reconciles(summary)


def test_service_catchup_collapses_to_zero_at_a_non_qualified_organization(api):
    """PRD §3.5: "The fifteen-year service catch-up is available only when the sponsor's
    `is_qualified_organization` is true and the participant's `years_of_service` is at
    least 15; when either condition fails, the capacity is zero."
    PRD §2.8: "A `TAX_EXEMPT_501C3` sponsor whose `organization_subtype` is `SCHOOL`,
    `CHURCH_ORG` or `OTHER` is therefore not a qualified organization."

    Design: Difficulty/combinatorial_formula/service_15yr_catchup_three_way_min_with_qualified_org_branch
    """
    set_clock()
    employer = register_nonqualified_employer()
    vendor = register_vendor()
    plan = create_active_plan(
        employer["id"], plan_name="Lakeside 403(b)", plan_type="PLAN_403B",
        reported_participant_count=120,
    )
    participant = register_participant(
        employer["id"], full_name="Cara Nolan", date_of_birth="1980-01-01",
        hire_date="2010-01-01", years_of_service=16,
        prior_employer_elective_deferrals_cents=500_000,
        cumulative_special_catchup_used_cents=1_350_000,
    )
    open_contract(
        participant["id"], plan["id"], vendor["id"], employer["id"],
        contract_number="NLA-C001", accumulated_benefit_cents=1_000_000,
        prior_years_elective_deferrals_cents=6_800_000,
    )

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": plan["id"]}
        )
    )

    assert summary["lifetime_elective_deferrals_cents"] == 7_300_000
    assert summary["service_15yr_catchup_capacity_cents"] == 0
    assert summary["age50_catchup_capacity_cents"] == 0
    assert summary["total_limit_cents"] == 2_450_000
    assert_limit_summary_reconciles(summary)


def test_457b_usable_catchup_is_the_greater_of_the_two(api):
    """PRD §3.5: "Inside the window, the capacity is the lesser of twice the basic limit
    and the basic limit increased by the participant's `underutilized_prior_limit_cents`,
    and from that lesser figure the basic limit itself is subtracted; equivalently, the
    participant may double up on the basic limit but only to the extent of the deferral
    room actually left unused in prior years."
    PRD §3.5: "The usable capacity is whichever of the two is larger, and
    `service_15yr_catchup_capacity_cents` is zero for this bucket."
    PRD §3.5: "The basic elective deferral limit is 24,500 dollars for the plan year, in
    either bucket. It is reported as `basic_limit_cents`."

    Design: Corner/calculations/catchup_457b_uses_greater_of_final_three_year_and_age_fifty
    """
    env = setup_plan_env(
        plan_type="PLAN_457B", num_vendors=1, plan_overrides={"plan_name": "Riverbend 457(b)"}
    )
    participant = register_participant(
        env["employer_id"], full_name="Fern Vela", date_of_birth="1963-01-01",
        hire_date="2000-01-01", years_of_service=26, underutilized_prior_limit_cents=1_000_000,
    )
    open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-F001", accumulated_benefit_cents=2_000_000,
    )

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )

    assert summary["bucket_plan_type"] == "PLAN_457B"
    assert summary["basic_limit_cents"] == 2_450_000
    assert summary["final_3yr_catchup_capacity_cents"] == 1_000_000
    assert summary["age50_catchup_capacity_cents"] == 800_000
    assert summary["usable_catchup_capacity_cents"] == 1_000_000
    assert summary["total_limit_cents"] == 3_450_000, "the greater of, never the sum"
    assert summary["service_15yr_catchup_capacity_cents"] == 0
    assert summary["ytd_gross_cents"] == 0
    assert summary["room_gross_cents"] == 3_450_000


def test_final_three_year_window_excludes_normal_retirement_age(api):
    """PRD §3.5: "The final-three-year catch-up is available only when
    `attained_age_at_year_end` is exactly 62, 63 or 64 — the three years immediately
    preceding a normal retirement age of 65. Age 61 and age 65 both yield zero."
    PRD §3.5: "The usable capacity is whichever of the two is larger, and
    `service_15yr_catchup_capacity_cents` is zero for this bucket."

    Design: Corner/calculations/final_three_year_window_excludes_normal_retirement_age
    """
    env = setup_plan_env(
        plan_type="PLAN_457B", num_vendors=1, plan_overrides={"plan_name": "Riverbend 457(b)"}
    )
    age_64 = register_participant(
        env["employer_id"], full_name="Sixty Four", date_of_birth="1962-01-01",
        hire_date="2000-01-01", years_of_service=26, underutilized_prior_limit_cents=1_000_000,
    )
    age_65 = register_participant(
        env["employer_id"], full_name="Sixty Five", date_of_birth="1961-01-01",
        hire_date="2000-01-01", years_of_service=26, underutilized_prior_limit_cents=1_000_000,
    )
    for participant, number in ((age_64, "NLA-64"), (age_65, "NLA-65")):
        open_contract(
            participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
            contract_number=number, accumulated_benefit_cents=2_000_000,
        )

    inside = validate_success(
        api.get_contribution_limit_summary(
            age_64["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    outside = validate_success(
        api.get_contribution_limit_summary(
            age_65["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )

    assert inside["final_3yr_catchup_capacity_cents"] == 1_000_000
    assert inside["usable_catchup_capacity_cents"] == 1_000_000
    assert inside["total_limit_cents"] == 3_450_000
    assert outside["final_3yr_catchup_capacity_cents"] == 0, "age 65 is outside the window"
    assert outside["age50_catchup_capacity_cents"] == 800_000
    assert outside["usable_catchup_capacity_cents"] == 800_000
    assert outside["total_limit_cents"] == 3_250_000


def test_top_hat_457_offers_no_age_fifty_catchup(api):
    """PRD §3.5: "The age-50 catch-up on a 457(b) bucket is 8,000 dollars only when
    `attained_age_at_year_end` is at least 50 *and* the plan's `is_governmental_457` is
    true; on a non-governmental top-hat 457(b) it is always zero."
    PRD §2.8: "Otherwise the plan is a `PLAN_457B`, and the regime is
    `GOVERNMENTAL_457_ALL_EMPLOYEES` when the sponsor is governmental and `TOP_HAT_457`
    when it is not."

    Design: Corner/calculations/top_hat_457_plan_offers_no_age_fifty_catchup
    """
    set_clock()
    employer = register_nonqualified_employer()
    vendor = register_vendor()
    plan = create_active_plan(
        employer["id"], plan_name="Lakeside 457(b)", plan_type="PLAN_457B",
        reported_participant_count=40,
    )
    participant = register_participant(
        employer["id"], full_name="Hedy Marsh", date_of_birth="1971-01-01",
        hire_date="2005-01-01", includible_compensation_cents=20_000_000,
        years_of_service=21, is_select_management_or_hce=True,
    )
    open_contract(
        participant["id"], plan["id"], vendor["id"], employer["id"],
        contract_number="NLA-H001", accumulated_benefit_cents=2_000_000,
    )

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": plan["id"]}
        )
    )

    assert plan["nondiscrimination_regime"] == "TOP_HAT_457"
    assert plan["is_governmental_457"] is False
    assert validate_success(
        api.get_participant(participant["id"], make_officer_headers())
    )["attained_age_at_year_end"] == 55
    assert summary["age50_catchup_capacity_cents"] == 0
    assert summary["final_3yr_catchup_capacity_cents"] == 0
    assert summary["usable_catchup_capacity_cents"] == 0
    assert summary["total_limit_cents"] == 2_450_000
    assert summary["room_gross_cents"] == 2_450_000


def test_deferral_aggregate_excludes_the_other_plan_type_bucket(api):
    """PRD §3.5: "The included set — the one reported as `included_vendor_account_ids` —
    is every contract of the participant whose `status` is `OPEN`, held under a plan
    whose `plan_type` equals the queried plan's `plan_type` and whose `status` is
    `ACTIVE` or `FROZEN`. Contracts under a `DRAFT` or `TERMINATED` plan are excluded,
    `CLOSED` contracts are excluded, and contracts in the other plan-type bucket are
    excluded."
    PRD §3.5: "Aggregation is bucketed by plan type, and the two buckets never mix:
    403(b) elective deferrals aggregate only with other 403(b) elective deferrals, and
    457(b) deferrals only with other 457(b) deferrals."

    Design: Corner/calculations/deferral_aggregate_excludes_other_bucket_and_draft_plan_contracts
    """
    set_clock()
    employer = register_employer()
    vendor = register_vendor()
    plan_403b = create_active_plan(employer["id"], plan_name="Riverbend 403(b)")
    plan_457b = create_active_plan(
        employer["id"], plan_name="Riverbend 457(b)", plan_type="PLAN_457B"
    )
    draft_plan = create_plan(employer["id"], plan_name="Riverbend Draft 403(b)")
    participant = register_participant(employer["id"])
    account_403b = open_contract(
        participant["id"], plan_403b["id"], vendor["id"], employer["id"],
        contract_number="NLA-403", accumulated_benefit_cents=5_000_000,
    )
    account_457b = open_contract(
        participant["id"], plan_457b["id"], vendor["id"], employer["id"],
        contract_number="NLA-457", accumulated_benefit_cents=5_000_000,
    )
    report_balance(
        account_403b["id"], vendor["id"], as_of_date="2026-07-31",
        accumulated_benefit_cents=5_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=1_000_000,
    )
    report_balance(
        account_457b["id"], vendor["id"], as_of_date="2026-07-31",
        accumulated_benefit_cents=5_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=900_000,
    )

    summary_403b = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": plan_403b["id"]}
        )
    )
    summary_457b = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": plan_457b["id"]}
        )
    )

    assert summary_403b["ytd_gross_cents"] == 1_000_000
    assert summary_403b["total_limit_cents"] == 3_250_000
    assert summary_403b["room_gross_cents"] == 2_250_000
    assert account_403b["id"] in summary_403b["included_vendor_account_ids"]
    assert account_457b["id"] not in summary_403b["included_vendor_account_ids"]
    assert summary_457b["ytd_gross_cents"] == 900_000
    assert summary_457b["usable_catchup_capacity_cents"] == 800_000
    assert summary_457b["total_limit_cents"] == 3_250_000
    assert summary_457b["room_gross_cents"] == 2_350_000

    rows, _meta = validate_paginated(
        api.list_vendor_accounts(make_officer_headers(), {"plan_id": draft_plan["id"]})
    )
    assert rows == [], "no contract exists under the DRAFT plan"


def test_annual_additions_ceiling_is_capped_by_includible_compensation(api):
    """PRD §3.5: "`annual_additions_cents` is the sum, over that set, of
    `ytd_elective_deferrals_cents` plus `ytd_employer_contributions_cents` on each
    contract. `annual_additions_limit_cents` is the lesser of 72,000 dollars and the
    participant's `includible_compensation_cents`. The ceiling is breached when the
    annual additions already recorded, increased by the amount of the election being
    approved, come out strictly greater than that limit — annual additions landing
    exactly on the limit pass."
    PRD §3.6: "Approval also runs the section 415(c) test described in §3.5 for a 403(b)
    plan; a breach is refused with `ERR_415C_LIMIT_EXCEEDED`."

    Design: Corner/calculations/annual_additions_415c_capped_by_includible_compensation
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=1)
    file_notice(env["plan_id"], env["employer_id"])
    participant = register_participant(
        env["employer_id"], full_name="Cap Tester", date_of_birth="1985-04-04",
        hire_date="2018-01-01", includible_compensation_cents=2_600_000, years_of_service=8,
    )
    account = open_contract(
        participant["id"], env["plan_id"], env["vendor_id"], env["employer_id"],
        contract_number="NLA-C415", accumulated_benefit_cents=3_000_000,
    )
    report_balance(
        account["id"], env["vendor_id"], as_of_date="2026-07-31",
        accumulated_benefit_cents=3_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=2_400_000,
        ytd_employer_contributions_cents=200_000,
    )
    determine_eligibility(env["plan_id"], participant["id"], "co-1")
    election = submit_election(
        participant["id"], env["plan_id"], account["id"], env["employer_id"],
        annual_deferral_amount_cents=40_000, effective_from="2026-09-01",
        effective_through="2026-12-31",
    )

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(), {"plan_id": env["plan_id"]}
        )
    )
    assert summary["annual_additions_cents"] == 2_600_000
    assert summary["annual_additions_limit_cents"] == 2_600_000
    assert summary["room_gross_cents"] == 50_000, (
        "the elective-deferral test alone would admit the 40000-cent election"
    )

    response = api.decide_election(
        election["id"], {"decision": "APPROVE"}, make_officer_headers("co-2")
    )
    validate_error(response, ApiErrorId.ERR_415C_LIMIT_EXCEEDED.value)
    assert validate_success(
        api.get_election(election["id"], make_officer_headers())
    )["state"] == "SUBMITTED"


def test_contribution_limit_summary_components_reconcile(api):
    """PRD §3.5: "`total_limit_cents` is always the basic limit plus the usable catch-up
    capacity for the bucket. `room_gross_cents` is the total limit less
    `ytd_gross_cents`, floored at zero; `room_verified_cents` is the total limit less
    `ytd_verified_cents`, floored at zero."
    PRD §3.5: "The verified set — reported as `verified_vendor_account_ids` — is the
    subset of the included set for which an information sharing agreement exists between
    that contract's plan and that contract's vendor with `status` `ACTIVE`,
    `shares_contribution_data` true and `data_stale` false."

    Design: Corner/endpoints/contribution_limit_summary_components_reconcile_with_each_other
    """
    env = setup_plan_env(plan_type="PLAN_403B", num_vendors=2)
    setup_active_agreement(env["plan_id"], env["vendor_ids"][0], env["employer_id"])
    setup_active_agreement(env["plan_id"], env["vendor_ids"][1], env["employer_id"])
    participant = register_participant(env["employer_id"])
    account_one = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][0], env["employer_id"],
        contract_number="NLA-0001", accumulated_benefit_cents=5_000_000,
    )
    account_two = open_contract(
        participant["id"], env["plan_id"], env["vendor_ids"][1], env["employer_id"],
        contract_number="CDR-0001", accumulated_benefit_cents=3_000_000,
    )
    report_balance(
        account_one["id"], env["vendor_ids"][0], as_of_date="2026-07-31",
        accumulated_benefit_cents=5_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=600_000,
        ytd_employer_contributions_cents=100_000,
    )
    report_balance(
        account_two["id"], env["vendor_ids"][1], as_of_date="2026-07-31",
        accumulated_benefit_cents=3_000_000, outstanding_loan_balance_cents=0,
        highest_outstanding_loan_12mo_cents=0, ytd_elective_deferrals_cents=400_000,
    )

    summary = validate_success(
        api.get_contribution_limit_summary(
            participant["id"], make_officer_headers(),
            {"plan_id": env["plan_id"], "plan_year": 2026},
        )
    )

    assert summary["basic_limit_cents"] == 2_450_000
    assert summary["age50_catchup_capacity_cents"] == 800_000
    assert summary["service_15yr_catchup_capacity_cents"] == 0
    assert summary["usable_catchup_capacity_cents"] == 800_000
    assert summary["total_limit_cents"] == 3_250_000
    assert summary["ytd_gross_cents"] == 1_000_000
    assert summary["ytd_verified_cents"] == 1_000_000
    assert summary["room_gross_cents"] == 2_250_000
    assert summary["room_verified_cents"] == 2_250_000
    assert summary["annual_additions_cents"] == 1_100_000
    assert summary["annual_additions_limit_cents"] == 7_200_000
    assert sorted(summary["included_vendor_account_ids"]) == sorted(
        [account_one["id"], account_two["id"]]
    )
    assert sorted(summary["verified_vendor_account_ids"]) == sorted(
        [account_one["id"], account_two["id"]]
    )
    assert summary["lifetime_elective_deferrals_cents"] == 1_000_000
    assert_limit_summary_reconciles(summary)
