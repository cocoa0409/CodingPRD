"""Uniqueness, cross-entity referential gates, temporal window gates, structural
completeness, interval overlap, and wage-floor validations (PRD §2.9, §3).

Queue B / Corner — section `validations`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_employer, create_beneficiary, create_cap_program, create_registration,
    create_pending_pwd, create_perm_case, create_lca, create_issued_pwd,
    setup_draft_h1b_petition, setup_quiet_period_perm_case, setup_recruiting_perm_case,
    setup_submitted_h1b_petition, setup_two_h1b_petitions_same_beneficiary,
    add_recruitment_step, issue_rfe, set_clock, make_employer_agent_headers,
    registration_payload, lca_payload,
)

DOL = TEST_USERS["dol_analyst_headers"]
USCIS = TEST_USERS["uscis_officer_headers"]


def test_duplicate_registration_same_employer_beneficiary_year_rejected(api):
    """PRD §3.5: "a second registration sharing the same `employer_id`,
    `beneficiary_id`, and `fiscal_year` as an existing one is rejected with
    `ERR_DUPLICATE_REGISTRATION` (409)."

    Design: Corner/validations/duplicate_registration_same_employer_beneficiary_year_rejected
    """
    emp = create_employer()
    ben = create_beneficiary(emp["id"])
    create_cap_program(2027, 5)
    create_registration(emp["id"], ben["id"], 2027)
    res = api.create_registration(registration_payload(emp["id"], ben["id"], 2027),
                                  make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_DUPLICATE_REGISTRATION, expected_status=409)


def test_perm_recruiting_requires_issued_pwd(api):
    """PRD §3.3: "Recruitment begins when the agent moves the case from `DRAFT` to
    `RECRUITING`. This is permitted only from `DRAFT`, and only when the
    referenced determination is `ISSUED` (otherwise `ERR_PWD_NOT_ISSUED`)".

    Design: Corner/validations/perm_recruiting_requires_issued_pwd
    """
    emp = create_employer()
    pwd = create_pending_pwd(emp["id"])  # never issued
    pc = create_perm_case(emp["id"], pwd["id"])
    hdr = make_employer_agent_headers(emp["id"])
    res = api.transition_perm_case(pc["id"], {"to_status": "RECRUITING"}, hdr)
    validate_error(res, ApiErrorId.ERR_PWD_NOT_ISSUED, expected_status=409)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "DRAFT"


def test_petition_submit_requires_selected_registration(api):
    """PRD §3.6: "the referenced registration must be `SELECTED` (otherwise
    `ERR_REGISTRATION_NOT_SELECTED`)".

    Design: Corner/validations/petition_submit_requires_selected_registration
    """
    ctx = setup_draft_h1b_petition(lca_certified=True, run_the_lottery=False)
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    res = api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr)
    validate_error(res, ApiErrorId.ERR_REGISTRATION_NOT_SELECTED, expected_status=409)
    assert validate_success(api.get_h1b_petition(ctx["petition"]["id"], hdr), 200)["status"] == "DRAFT"


def test_petition_submit_requires_worksite_in_lca_areas(api):
    """PRD §3.6: "the `worksite_area` must be one of the application's
    `worksite_areas` (otherwise `ERR_WORKSITE_NOT_COVERED`)."

    Design: Corner/validations/petition_submit_requires_worksite_in_lca_areas
    """
    ctx = setup_draft_h1b_petition(
        lca_certified=True, run_the_lottery=True,
        lca_overrides={"worksite_areas": ["AREA_A"], "area_wage_map": {"AREA_A": 10000000}},
        petition_overrides={"worksite_area": "AREA_B"})
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    res = api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr)
    validate_error(res, ApiErrorId.ERR_WORKSITE_NOT_COVERED, expected_status=409)


def test_registration_with_petition_cannot_be_withdrawn(api):
    """PRD §3.5: "Withdrawal is blocked while any `H1BPetition` references the
    registration: if a petition names this registration, the request is rejected
    with `ERR_REGISTRATION_HAS_PETITION`."

    Design: Corner/validations/registration_with_petition_cannot_be_withdrawn
    """
    ctx = setup_draft_h1b_petition(lca_certified=True, run_the_lottery=True)
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    res = api.transition_registration(ctx["registration"]["id"], {"to_status": "WITHDRAWN"}, hdr)
    validate_error(res, ApiErrorId.ERR_REGISTRATION_HAS_PETITION, expected_status=409)
    assert validate_success(api.get_registration(ctx["registration"]["id"], hdr), 200)["status"] == "SELECTED"


def test_perm_filing_before_quiet_period_end_rejected(api):
    """PRD §3.3: "The quiet period must have fully elapsed: the current clock must
    be at or after `quiet_period_end`, otherwise `ERR_QUIET_PERIOD_NOT_ELAPSED`."

    Design: Corner/validations/perm_filing_before_quiet_period_end_rejected
    """
    employer, pwd, pc = setup_quiet_period_perm_case(quiet_clock="2026-06-05T00:00:00Z")
    hdr = make_employer_agent_headers(employer["id"])
    set_clock("2026-06-20T00:00:00Z")  # before quiet_period_end 2026-07-05
    res = api.transition_perm_case(pc["id"], {"to_status": "FILED"}, hdr)
    validate_error(res, ApiErrorId.ERR_QUIET_PERIOD_NOT_ELAPSED, expected_status=422)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "QUIET_PERIOD"


def test_perm_filing_after_180_day_validity_rejected(api):
    """PRD §3.3: "the overall PERM window must not have lapsed: the current clock
    must be at or before `recruitment_start` plus 180 days, otherwise
    `ERR_PERM_VALIDITY_EXPIRED`."

    Design: Corner/validations/perm_filing_after_180_day_validity_rejected
    """
    employer, pwd, pc = setup_quiet_period_perm_case(quiet_clock="2026-06-05T00:00:00Z")
    hdr = make_employer_agent_headers(employer["id"])
    # recruitment_start 2026-05-01 + 180 days == 2026-10-28; filing at 2026-11-01 is past.
    set_clock("2026-11-01T00:00:00Z")
    res = api.transition_perm_case(pc["id"], {"to_status": "FILED"}, hdr)
    validate_error(res, ApiErrorId.ERR_PERM_VALIDITY_EXPIRED, expected_status=422)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "QUIET_PERIOD"


def test_quiet_period_requires_two_newspaper_ads(api):
    """PRD §3.3: "there must exist at least one `ACTIVE` step of `step_type`
    `JOB_ORDER` and at least two `ACTIVE` steps of `step_type` `NEWSPAPER_AD`, or
    the request is rejected with `ERR_RECRUITMENT_INCOMPLETE`."

    Design: Corner/validations/quiet_period_requires_two_newspaper_ads
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    add_recruitment_step(employer["id"], pc["id"], step_type="JOB_ORDER",
                         start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    add_recruitment_step(employer["id"], pc["id"], step_type="NEWSPAPER_AD",
                         start_date="2026-05-04T00:00:00Z", end_date="2026-05-04T00:00:00Z")
    set_clock("2026-06-05T00:00:00Z")  # >= 30 days: temporal gate passes
    res = api.transition_perm_case(pc["id"], {"to_status": "QUIET_PERIOD"}, hdr)
    validate_error(res, ApiErrorId.ERR_RECRUITMENT_INCOMPLETE, expected_status=422)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "RECRUITING"


def test_employment_interval_genuine_overlap_rejected_on_approval(api):
    """PRD §3.6: "no other `APPROVED` petition for the *same* `beneficiary_id` and
    `worksite_area` may have an employment interval overlapping
    `[employment_start, employment_end)`. That interval is **half-open**, so two
    petitions that merely abut — one ending exactly when the next begins — do not
    conflict, whereas any genuine overlap is rejected with `ERR_EMPLOYMENT_OVERLAP`
    (409)."

    Design: Corner/validations/employment_interval_genuine_overlap_rejected_on_approval
    """
    ctx = setup_two_h1b_petitions_same_beneficiary(
        pet1_start="2026-10-01T00:00:00Z", pet1_end="2028-10-01T00:00:00Z",
        pet2_start="2027-10-01T00:00:00Z", pet2_end="2029-10-01T00:00:00Z")
    res = api.transition_h1b_petition(ctx["petition2"]["id"], {"to_status": "APPROVED"}, USCIS)
    validate_error(res, ApiErrorId.ERR_EMPLOYMENT_OVERLAP, expected_status=409)
    assert validate_success(api.get_h1b_petition(ctx["petition2"]["id"], USCIS), 200)["status"] == "SUBMITTED"


def test_lca_certify_wage_one_cent_below_prevailing_rejected(api):
    """PRD §3.4: "Certification is defined only from `DRAFT`, and requires that
    `offered_wage_cents` be at least `prevailing_wage_cents` (otherwise
    `ERR_WAGE_BELOW_PREVAILING`)."

    Design: Corner/validations/lca_certify_wage_one_cent_below_prevailing_rejected
    """
    emp = create_employer()
    lca = create_lca(emp["id"], offered_wage_cents=9999999, prevailing_wage_cents=10000000)
    res = api.transition_lca(lca["id"], {"to_status": "CERTIFIED"}, DOL)
    validate_error(res, ApiErrorId.ERR_WAGE_BELOW_PREVAILING, expected_status=422)
    assert validate_success(api.get_lca(lca["id"], DOL), 200)["status"] == "DRAFT"


def test_perm_recruiting_wage_below_prevailing_rejected(api):
    """PRD §3.3: "the case's `offered_wage_cents` is at least the determination's
    `prevailing_wage_cents` (otherwise `ERR_WAGE_BELOW_PREVAILING`)."

    Design: Corner/validations/perm_recruiting_wage_below_prevailing_rejected
    """
    emp = create_employer()
    pwd = create_issued_pwd(emp["id"], oes_wage_cents=10000000)
    pc = create_perm_case(emp["id"], pwd["id"], offered_wage_cents=9999999)
    hdr = make_employer_agent_headers(emp["id"])
    res = api.transition_perm_case(pc["id"], {"to_status": "RECRUITING"}, hdr)
    validate_error(res, ApiErrorId.ERR_WAGE_BELOW_PREVAILING, expected_status=422)
    assert validate_success(api.get_perm_case(pc["id"], hdr), 200)["status"] == "DRAFT"


def test_recruitment_steps_different_types_same_interval_allowed(api):
    """PRD §3.4: "Different step types never conflict with one another."

    Design: Corner/validations/recruitment_steps_different_types_same_interval_allowed
    """
    employer, pwd, pc = setup_recruiting_perm_case()
    hdr = make_employer_agent_headers(employer["id"])
    add_recruitment_step(employer["id"], pc["id"], step_type="JOB_ORDER",
                         start_date="2026-05-01T00:00:00Z", end_date="2026-05-31T00:00:00Z")
    res = api.create_recruitment_step(
        {"perm_case_id": pc["id"], "step_type": "NEWSPAPER_AD",
         "start_date": "2026-05-01T00:00:00Z", "end_date": "2026-05-31T00:00:00Z"}, hdr)
    step = validate_success(res, 201)
    assert step["status"] == "ACTIVE"


def test_rfe_response_exactly_at_due_date_boundary_succeeds(api):
    """PRD §3.6: "The employer answers by moving the petition back from
    `RFE_ISSUED` to `SUBMITTED`, permitted only from `RFE_ISSUED` and only while
    the current clock is at or before `rfe_due_date` (otherwise `ERR_RFE_EXPIRED`);
    a successful response sets `rfe_status` to `RESPONDED`".

    Design: Corner/validations/rfe_response_exactly_at_due_date_boundary_succeeds
    """
    ctx = setup_submitted_h1b_petition()
    issue_rfe(ctx["petition"]["id"])  # due 2026-07-27
    set_clock("2026-07-27T00:00:00Z")  # exactly at due date (inclusive, not past)
    hdr = make_employer_agent_headers(ctx["employer"]["id"])
    responded = validate_success(
        api.transition_h1b_petition(ctx["petition"]["id"], {"to_status": "SUBMITTED"}, hdr), 200)
    assert responded["status"] == "SUBMITTED"
    assert responded["rfe_status"] == "RESPONDED"
