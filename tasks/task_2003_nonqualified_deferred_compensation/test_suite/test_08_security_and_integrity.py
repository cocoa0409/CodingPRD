"""RBAC denials, auth-header enforcement, ownership, segregation of duties, and
cross-aggregate referential integrity.

PRD §2.1 (roles/identity), §2.8 (pipeline), §2.9 (segregation of duties).
"""
from test_helpers import (
    TEST_USERS,
    add_fund,
    add_window,
    advance_clock,
    append_record,
    build_user_headers,
    create_active_plan,
    create_crediting_run_payload,
    create_election,
    create_rabbi_trust_payload,
    enroll_participant,
    funding_event_payload,
    get_case,
    get_election,
    get_operational_failure,
    get_plan,
    make_compliance_officer_headers,
    make_participant_headers,
    open_account,
    open_separation_case,
    plan_version,
    post_deferral,
    setup_operational_failure,
    settle_account,
    submit_election,
    validate_error,
    validate_success,
)

PS = TEST_USERS["plan_sponsor_headers"]
BA = TEST_USERS["benefits_admin_headers"]
CO = TEST_USERS["compliance_officer_headers"]
TO = TEST_USERS["trust_officer_headers"]
ADMIN = TEST_USERS["platform_admin_headers"]


def test_role_denial_sweep_exclusive_operations(api):
    """PRD §2.1: "Access to specific operations is restricted by role; an
    attempt to perform an action outside the caller's designated role is
    rejected with `ERR_FORBIDDEN_ROLE`."
    PRD §4: plan creation is PlanSponsor-only; separation determination is
    ComplianceOfficer-only; participant enrollment is BenefitsAdministrator-only;
    crediting runs are BenefitsAdministrator-only; the test clock is
    PlatformAdmin-only.

    Design: Corner/rbac/role_denial_sweep_exclusive_operations
    """
    plan = create_active_plan(name="Plan RB", distribution_events_allowed=["SEPARATION"])
    plan_v = plan_version(plan["id"])
    participant = enroll_participant(plan["id"], employee_ref="EMP-RB")
    case = open_separation_case(participant["id"], "2027-03-15", "TERMINATION")
    append_record(case["id"], "2024-03-15", "2027-03-15", 0)
    assert get_case(case["id"])["status"] == "EVIDENCE_SUBMITTED"

    r1 = api.create_plan({
        "name": "Plan NOPE", "effective_date": "2026-01-01",
        "distribution_events_allowed": ["SEPARATION"],
        "officer_comp_threshold_cents": 20000000,
    }, make_participant_headers(participant["id"]))
    validate_error(r1, "ERR_FORBIDDEN_ROLE", expected_status=403)

    r2 = api.determine_case(case["id"], {"outcome": "CONFIRMED_SEPARATION"},
                            build_user_headers("ba-9", "BenefitsAdministrator"))
    validate_error(r2, "ERR_FORBIDDEN_ROLE", expected_status=403)

    r3 = api.create_participant({
        "plan_id": plan["id"], "employee_ref": "EMP-RB2", "hire_date": "2023-01-02",
        "initial_eligibility_date": "2026-01-05", "annual_compensation_cents": 30000000,
    }, CO)
    validate_error(r3, "ERR_FORBIDDEN_ROLE", expected_status=403)

    r4 = api.create_crediting_run(create_crediting_run_payload(
        plan["id"], plan_version(plan["id"]), period_start="2027-01-01",
        period_end="2027-02-01"), TO)
    validate_error(r4, "ERR_FORBIDDEN_ROLE", expected_status=403)

    r5 = api.set_clock("2027-01-01T00:00:00Z", PS)
    validate_error(r5, "ERR_FORBIDDEN_ROLE", expected_status=403)

    assert get_case(case["id"])["status"] == "EVIDENCE_SUBMITTED", "denied calls do not mutate"
    assert plan_version(plan["id"]) == plan_v, "plan version unchanged by denied calls"


def test_missing_auth_header_unauthenticated(api):
    """PRD §2.1: "A request whose headers are missing or empty, or whose
    `X-User-Role` does not name one of these six roles, is rejected with
    `ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER`."

    The X-User-ID / X-User-Role headers are omitted entirely on an otherwise
    valid create.

    Design: Corner/rbac/missing_auth_header_unauthenticated
    """
    res = api.create_plan({
        "name": "Plan NA", "effective_date": "2026-01-01",
        "distribution_events_allowed": ["SEPARATION"],
        "officer_comp_threshold_cents": 20000000,
    }, headers={})
    validate_error(res, "ERR_MISSING_OR_INVALID_USER_CONTEXT_HEADER", expected_status=400)


def test_participant_ownership_mismatch_rejected(api):
    """PRD §2.1: "When `X-User-Role` is `Participant`, `X-User-ID` is the `id`
    of the acting `Participant` record; ownership checks on any resource that
    references a participant — most directly a deferral election's
    `participant_id`, or an account's `participant_id` reached through the
    target account — compare that foreign-key field to `X-User-ID`, and a
    mismatch is rejected with `ERR_RESOURCE_OWNERSHIP_MISMATCH`."

    P2 cannot submit P1's election and cannot draw on P1's account, even though
    Participant is the correct role for both endpoints.

    Design: Corner/rbac/participant_ownership_mismatch_rejected
    """
    plan = create_active_plan(name="Plan OM", distribution_events_allowed=["FIXED_TIME"])
    fund = add_fund(plan["id"])
    window = add_window(plan["id"])
    p1 = enroll_participant(plan["id"], employee_ref="EMP-O1")
    p2 = enroll_participant(plan["id"], employee_ref="EMP-O2")
    acct1 = open_account(p1["id"], plan["id"])

    advance_clock("2026-10-15T00:00:00Z")
    e1 = create_election(p1["id"], window["id"], fund["id"])

    blocked_submit = api.submit_election(e1["id"], make_participant_headers(p2["id"]))
    validate_error(blocked_submit, "ERR_RESOURCE_OWNERSHIP_MISMATCH", expected_status=403)

    blocked_draw = api.create_distribution_request({
        "account_id": acct1["id"], "event_type": "FIXED_TIME", "fixed_date": "2027-06-01",
        "requested_amount_cents": 1000,
    }, make_participant_headers(p2["id"]))
    validate_error(blocked_draw, "ERR_RESOURCE_OWNERSHIP_MISMATCH", expected_status=403)

    assert get_election(e1["id"])["status"] == "DRAFT", "election unchanged"


def test_segregation_of_duties_same_user_rejected(api):
    """PRD §2.9: "A separation-case determination must be rendered by a
    `ComplianceOfficer` whose `X-User-ID` differs from the case's
    `opened_by_user_id`; an income-inclusion assessment on an operational
    failure must be rendered by a `ComplianceOfficer` whose `X-User-ID` differs
    from the case's `reported_by_user_id`. Either self-adjudication is rejected
    with `ERR_SEGREGATION_OF_DUTIES` (HTTP 403)."

    The opener/reporter user id "ba-1" is reused with the ComplianceOfficer
    role: both self-adjudications are refused.

    Design: Corner/rbac/segregation_of_duties_same_user_rejected
    """
    plan = create_active_plan(name="Plan SD1", distribution_events_allowed=["SEPARATION"])
    participant = enroll_participant(plan["id"], employee_ref="EMP-SD1")
    account = open_account(participant["id"], plan["id"])

    case = open_separation_case(participant["id"], "2027-03-15", "TERMINATION")
    assert case["opened_by_user_id"] == "ba-1"
    append_record(case["id"], "2024-03-15", "2027-03-15", 0)  # avg 0 < 5000

    failure = setup_operational_failure(account["id"], failure_type="EARLY_PAYMENT",
                                        failure_date="2026-07-01", amount_cents=50000)
    assert failure["reported_by_user_id"] == "ba-1"
    quantified = validate_success(api.quantify_failure(
        failure["id"], {"correction_credit_cents": 0}, CO), 200)
    assert quantified["status"] == "QUANTIFIED"

    sod1 = api.determine_case(case["id"], {"outcome": "CONFIRMED_SEPARATION"},
                              make_compliance_officer_headers("ba-1"))
    validate_error(sod1, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    sod2 = api.assess_inclusion(failure["id"], make_compliance_officer_headers("ba-1"))
    validate_error(sod2, "ERR_SEGREGATION_OF_DUTIES", expected_status=403)

    assert get_case(case["id"])["status"] == "EVIDENCE_SUBMITTED", "unchanged"
    assert get_operational_failure(failure["id"])["status"] == "QUANTIFIED", "unchanged"


def test_cross_reference_integrity_sweep(api):
    """PRD §3.2: "Creation requires an `ACTIVE` plan, an `ACTIVE` participant
    (`ERR_PARTICIPANT_NOT_ACTIVE`), plan coherence across the three references —
    the participant's `plan_id`, the window's `plan_id`, and the fund's
    `plan_id` must all agree, else `ERR_CROSS_PLAN_REFERENCE`".
    PRD §3.3: "the account's `plan_id` must equal the participant's own
    `plan_id`, else `ERR_CROSS_PLAN_REFERENCE`".
    PRD §3.2: "Posting requires the election to be `LOCKED`
    (`ERR_ELECTION_NOT_MODIFIABLE`), an `ACTIVE` plan, an account already opened
    for the election's participant and plan (`ERR_ACCOUNT_REQUIRED`), and that
    account not `CLOSED` (`ERR_ACCOUNT_CLOSED`)."
    PRD §3.7: "A `CIC_MANDATORY_FUNDING` must be positive, is accepted only when
    a verified change-in-control event exists for the plan
    (`ERR_NO_VERIFIED_CIC`)".
    PRD §3.7: "One invariant binds all three types: assets may never be driven
    below zero (`ERR_NEGATIVE_TRUST_ASSETS`)."

    Design: Corner/errors/cross_reference_integrity_sweep
    """
    plan_a = create_active_plan(name="Plan XA", distribution_events_allowed=["SEPARATION"])
    plan_b = create_active_plan(name="Plan XB", distribution_events_allowed=["SEPARATION"])
    fund_b = add_fund(plan_b["id"], ticker="FIXB")
    fund_a = add_fund(plan_a["id"], ticker="FIXA")
    window_a = add_window(plan_a["id"])
    p1 = enroll_participant(plan_a["id"], employee_ref="EMP-X1")
    p2 = enroll_participant(plan_a["id"], employee_ref="EMP-X2")

    advance_clock("2026-10-15T00:00:00Z")  # window_a OPEN
    e2 = create_election(p2["id"], window_a["id"], fund_a["id"])
    submit_election(e2["id"], p2["id"])

    trust = validate_success(api.create_rabbi_trust(
        create_rabbi_trust_payload(plan_a["id"], funding_target_bp=10000), PS), 201)

    xfund = api.create_deferral_election({
        "participant_id": p1["id"], "election_window_id": window_a["id"],
        "election_type": "GENERAL", "deferral_percent_bp": 5000,
        "notional_fund_id": fund_b["id"],
    }, make_participant_headers(p1["id"]))
    validate_error(xfund, "ERR_CROSS_PLAN_REFERENCE", expected_status=409)

    xacct = api.create_account({"participant_id": p1["id"], "plan_id": plan_b["id"]}, BA)
    validate_error(xacct, "ERR_CROSS_PLAN_REFERENCE", expected_status=409)

    advance_clock("2027-01-01T00:00:00Z")  # e2 LOCKED; P2 still has no account
    assert get_election(e2["id"])["status"] == "LOCKED"
    noacct = api.post_deferral(e2["id"], {
        "amount_cents": 1000, "service_period_start": "2027-01-01",
        "service_period_end": "2027-01-31"}, BA)
    validate_error(noacct, "ERR_ACCOUNT_REQUIRED", expected_status=409)

    nocic = api.post_funding_event(
        trust["id"], funding_event_payload("CIC_MANDATORY_FUNDING", 1000), TO)
    validate_error(nocic, "ERR_NO_VERIFIED_CIC", expected_status=409)

    negative = api.post_funding_event(
        trust["id"], funding_event_payload("VALUATION_ADJUSTMENT", -5000), TO)
    validate_error(negative, "ERR_NEGATIVE_TRUST_ASSETS", expected_status=402)
