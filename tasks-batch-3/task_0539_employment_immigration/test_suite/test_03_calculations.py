"""Prevailing wage, filing-fee tiers, PAF scoring, deterministic lottery, running
wage obligation, quiet-period window, and aggregate proration (PRD §3).

Queue B / Corner — section `calculations`.
"""
from test_helpers import (
    api_client, validate_success, ApiErrorId, TEST_USERS,
    create_employer, create_pending_pwd, issue_pwd, create_beneficiary,
    create_certified_lca, create_cap_program, create_registration, run_lottery,
    setup_draft_h1b_petition, setup_recruiting_perm_case, add_recruitment_step,
    set_clock, make_employer_agent_headers,
    lca_payload,
)

DOL = TEST_USERS["dol_analyst_headers"]
USCIS = TEST_USERS["uscis_officer_headers"]


def test_prevailing_wage_uses_survey_wage_for_employer_survey_source(api):
    """PRD §3.2: "it is set equal to `oes_wage_cents` when `wage_source` is `OES`,
    and equal to `survey_wage_cents` when `wage_source` is `EMPLOYER_SURVEY`."

    Design: Corner/calculations/prevailing_wage_uses_survey_wage_for_employer_survey_source
    """
    emp = create_employer()
    pwd = create_pending_pwd(emp["id"], wage_source="EMPLOYER_SURVEY",
                             oes_wage_cents=10000000, survey_wage_cents=12500000)
    issued = issue_pwd(emp["id"], pwd["id"])
    assert issued["prevailing_wage_cents"] == 12500000


def test_h1b_filing_fee_amended_pays_base_only(api):
    """PRD §3.6: "An amended petition skips all three add-ons and pays only the
    46000-cent base."

    Design: Corner/calculations/h1b_filing_fee_amended_pays_base_only
    """
    ctx = setup_draft_h1b_petition(
        employer_overrides={"employee_count": 60, "h1b_dependent": True},
        petition_overrides={"is_amended": True})
    assert ctx["petition"]["filing_fee_cents"] == 46000


def test_h1b_filing_fee_small_employer_not_dependent(api):
    """PRD §3.6: "Start from a base fee of 46000 cents. If the petition is *not*
    amended, add the fraud-prevention fee of 50000 cents; then add the ACWIA
    training fee, which is 75000 cents when the employer's `employee_count` is at
    most 25 and 150000 cents when it exceeds 25; and then, only when the
    employer's `employee_count` is greater than 50 *and* its `h1b_dependent` flag
    is true, add the Public Law 114-113 fee of 400000 cents."

    Design: Corner/calculations/h1b_filing_fee_small_employer_not_dependent
    """
    ctx = setup_draft_h1b_petition(
        employer_overrides={"employee_count": 10},
        petition_overrides={"is_amended": False})
    assert ctx["petition"]["filing_fee_cents"] == 171000


def test_h1b_filing_fee_large_employer_not_dependent_no_pl_fee(api):
    """PRD §3.6: "then add the ACWIA training fee, which is 75000 cents when the
    employer's `employee_count` is at most 25 and 150000 cents when it exceeds 25;
    and then, only when the employer's `employee_count` is greater than 50 *and*
    its `h1b_dependent` flag is true, add the Public Law 114-113 fee of 400000
    cents."

    Design: Corner/calculations/h1b_filing_fee_large_employer_not_dependent_no_pl_fee
    """
    ctx = setup_draft_h1b_petition(
        employer_overrides={"employee_count": 60, "h1b_dependent": False},
        petition_overrides={"is_amended": False})
    assert ctx["petition"]["filing_fee_cents"] == 246000


def test_paf_completeness_all_four_docs_scores_100_complete(api):
    """PRD §3.4: "each of `has_wage_rate`, `has_prevailing_wage_doc`,
    `has_notice_of_filing`, and `has_actual_wage_memo` that is true contributes 25
    points, for a score between 0 and 100. The audit then sets `paf_status` to
    `COMPLETE` when the score is exactly 100, and to `DEFICIENT` otherwise."

    Design: Corner/calculations/paf_completeness_all_four_docs_scores_100_complete
    """
    emp = create_employer()
    lca = validate_success(api.create_lca(
        lca_payload(emp["id"], has_wage_rate=True, has_prevailing_wage_doc=True,
                    has_notice_of_filing=True, has_actual_wage_memo=True),
        make_employer_agent_headers(emp["id"])), 201)
    audited = validate_success(api.audit_paf(lca["id"], TEST_USERS["compliance_auditor_headers"]), 200)
    assert audited["paf_completeness_score"] == 100
    assert audited["paf_status"] == "COMPLETE"


def test_paf_completeness_three_docs_scores_75_deficient(api):
    """PRD §3.4: "each of `has_wage_rate`, `has_prevailing_wage_doc`,
    `has_notice_of_filing`, and `has_actual_wage_memo` that is true contributes 25
    points, for a score between 0 and 100. The audit then sets `paf_status` to
    `COMPLETE` when the score is exactly 100, and to `DEFICIENT` otherwise."

    Design: Corner/calculations/paf_completeness_three_docs_scores_75_deficient
    """
    emp = create_employer()
    lca = validate_success(api.create_lca(
        lca_payload(emp["id"], has_wage_rate=True, has_prevailing_wage_doc=True,
                    has_notice_of_filing=True, has_actual_wage_memo=False),
        make_employer_agent_headers(emp["id"])), 201)
    audited = validate_success(api.audit_paf(lca["id"], TEST_USERS["compliance_auditor_headers"]), 200)
    assert audited["paf_completeness_score"] == 75
    assert audited["paf_status"] == "DEFICIENT"


def test_lottery_oversubscribed_fills_seats_by_created_at_order(api):
    """PRD §3.5: "sorts those candidates by `created_at` ascending (and only
    `created_at`, never `id`, as the tie-break), and walks them in that order:
    each candidate whose position is below the number of available seats is moved
    from `SUBMITTED` to `SELECTED`, and the rest are moved from `SUBMITTED` to
    `NOT_SELECTED`."

    Design: Corner/calculations/lottery_oversubscribed_fills_seats_by_created_at_order
    """
    emp = create_employer()
    cap = create_cap_program(fiscal_year=2027, selection_quota=2)
    ben1 = create_beneficiary(emp["id"])
    reg1 = create_registration(emp["id"], ben1["id"], 2027)
    ben2 = create_beneficiary(emp["id"])
    create_registration(emp["id"], ben2["id"], 2027)
    ben3 = create_beneficiary(emp["id"])
    reg3 = create_registration(emp["id"], ben3["id"], 2027)
    program = run_lottery(cap["id"])
    assert program["selected_count"] == 2
    assert program["available_seats"] == 0
    assert validate_success(api.get_registration(reg1["id"], USCIS), 200)["status"] == "SELECTED"
    assert validate_success(api.get_registration(reg3["id"], USCIS), 200)["status"] == "NOT_SELECTED"


def test_employer_wage_obligation_sums_two_certified_lcas(api):
    """PRD §3.1: "It is defined as the sum of `required_wage_cents` over exactly
    those of the employer's labor condition applications whose `status` is
    `CERTIFIED`."

    Design: Corner/calculations/employer_wage_obligation_sums_two_certified_lcas
    """
    emp = create_employer()
    create_certified_lca(emp["id"], worksite_areas=["AREA_A"], area_wage_map={"AREA_A": 10000000},
                         offered_wage_cents=12000000, prevailing_wage_cents=10000000)
    create_certified_lca(emp["id"], worksite_areas=["AREA_B"], area_wage_map={"AREA_B": 11000000},
                         offered_wage_cents=11000000, prevailing_wage_cents=11000000)
    emp_after = validate_success(api.get_employer(emp["id"], make_employer_agent_headers(emp["id"])), 200)
    assert emp_after["total_wage_obligation_cents"] == 23000000


def test_recruitment_window_quiet_period_end_is_recruitment_end_plus_30_days(api):
    """PRD §3.3: "On success the system stamps `recruitment_end` to the current
    clock and computes `quiet_period_end` as `recruitment_end` plus 30 days — the
    earliest instant at which filing becomes permissible."

    Design: Corner/calculations/recruitment_window_quiet_period_end_is_recruitment_end_plus_30_days
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    add_recruitment_step(employer["id"], pc["id"], step_type="JOB_ORDER",
                         start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    add_recruitment_step(employer["id"], pc["id"], step_type="NEWSPAPER_AD",
                         start_date="2026-05-04T00:00:00Z", end_date="2026-05-04T00:00:00Z")
    add_recruitment_step(employer["id"], pc["id"], step_type="NEWSPAPER_AD",
                         start_date="2026-05-11T00:00:00Z", end_date="2026-05-11T00:00:00Z")
    set_clock("2026-06-05T00:00:00Z")
    quiet = validate_success(api.transition_perm_case(pc["id"], {"to_status": "QUIET_PERIOD"}, hdr), 200)
    assert quiet["quiet_period_end"] == "2026-07-05T00:00:00Z"


def test_aggregate_wage_two_areas_full_time_no_proration(api):
    """PRD §3.4: "iterating over `worksite_areas` in list order, each area's entry
    in `area_wage_map` is multiplied by `hours_per_week`, divided by 40, and
    rounded half up to whole cents; those per-area rounded amounts are then
    summed."

    Design: Corner/calculations/aggregate_wage_two_areas_full_time_no_proration
    """
    emp = create_employer()
    lca = validate_success(api.create_lca(
        lca_payload(emp["id"], worksite_areas=["AREA_A", "AREA_B"],
                    area_wage_map={"AREA_A": 10000000, "AREA_B": 20000000},
                    hours_per_week=40, prevailing_wage_cents=10000000),
        make_employer_agent_headers(emp["id"])), 201)
    assert lca["aggregate_wage_obligation_cents"] == 30000000
