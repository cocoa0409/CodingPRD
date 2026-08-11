"""Corner tests for OCC stale-version rejection and RBAC role denials."""
from test_helpers import (
    api_client, TEST_USERS, ApiErrorId,
    validate_success, validate_error, get_success_data,
    reset_clock, create_case, create_case_in_fieldwork, create_triaged_case,
    create_plan_payload, create_report_payload, create_disclosure_payload,
    make_investigator_headers, make_manager_headers, make_hr_headers,
    make_gc_headers, TEST_DEFAULTS,
)

IC = TEST_USERS["intake_coordinator_headers"]
INV = TEST_USERS["investigator_headers"]
MGR = TEST_USERS["manager_headers"]
HR = TEST_USERS["hr_headers"]
GC = TEST_USERS["gc_headers"]
CLO = TEST_USERS["clo_headers"]
AUD = TEST_USERS["auditor_headers"]
ADMIN = TEST_USERS["admin_headers"]


def test_occ_stale_version_on_plan_create_rejected(api):
    """PRD §2.7: "Each of these requests must carry an
    `expected_case_version` field whose value equals the parent `Case`'s
    current `version` at the time the server processes the request. A
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412)..."

    Design: Corner/errors/occ_stale_version_on_plan_create_rejected
    """
    reset_clock()
    case = get_success_data(api.create_case(
        {"title": "OCCPlan", "allegation_category": "FRAUD", "severity": "HIGH",
         "department": "Finance", "lead_investigator_id": "inv-lead-1"},
        IC,
    ))
    v0 = case["version"]
    get_success_data(api.transition_case(
        case["id"],
        {"to_status": "TRIAGED", "severity": "HIGH", "department": "Finance"},
        IC,
    ))
    resp = api.create_plan(
        case["id"],
        create_plan_payload(expected_case_version=v0),
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_stale_version_on_report_create_rejected(api):
    """PRD §2.7: "Three creation endpoints are protected by optimistic
    concurrency control on the parent `Case`: creating an
    `InvestigationPlan`, creating a `CaseReport`, and creating a
    `SelfDisclosureDecision`. Each of these requests must carry an
    `expected_case_version` field whose value equals the parent `Case`'s
    current `version` at the time the server processes the request. A
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
    the client from overwriting a plan, report, or disclosure whose
    underlying case it has not observed."

    Design: Corner/errors/occ_stale_version_on_report_create_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="OCCRep", allegation_category="POLICY_VIOLATION",
        severity="MEDIUM", department="Ops",
    )
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    v1 = get_success_data(api.get_case(case["id"], INV))["version"]
    # Disclosure creation advances Case.version
    get_success_data(api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(expected_case_version=v1),
        GC,
    ))
    resp = api.create_report(
        case["id"],
        create_report_payload(
            title="Stale Report", distribution_tier="RESTRICTED",
            distribution_list=["gc-1"], report_privilege_type="NONE",
            expected_case_version=v1,
        ),
        inv1,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_occ_stale_version_on_disclosure_create_rejected(api):
    """PRD §2.7: "Three creation endpoints are protected by optimistic
    concurrency control on the parent `Case`: creating an
    `InvestigationPlan`, creating a `CaseReport`, and creating a
    `SelfDisclosureDecision`. Each of these requests must carry an
    `expected_case_version` field whose value equals the parent `Case`'s
    current `version` at the time the server processes the request. A
    mismatch is rejected with `ERR_STALE_VERSION` (HTTP 412), preventing
    the client from overwriting a plan, report, or disclosure whose
    underlying case it has not observed."

    Design: Corner/errors/occ_stale_version_on_disclosure_create_rejected
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="OCCDisc", allegation_category="BRIBERY", severity="CRITICAL",
        department="Sales",
    )
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    v1 = get_success_data(api.get_case(case["id"], GC))["version"]
    get_success_data(api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(regulator="SEC", expected_case_version=v1),
        GC,
    ))
    resp = api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(
            regulator="DOJ", decision_deadline="2026-05-20T00:00:00Z",
            expected_case_version=v1,
        ),
        GC,
    )
    validate_error(resp, ApiErrorId.ERR_STALE_VERSION, expected_status=412)


def test_intake_coordinator_cannot_approve_plan(api):
    """PRD §3.2: "An `InvestigationsManager` then decides. Approval
    transitions `SUBMITTED` to `APPROVED`..."
    PRD §4 endpoint table restricts POST /api/plans/{id}/transition to
    `Investigator, InvestigationsManager`."

    Design: Corner/rbac/intake_coordinator_cannot_approve_plan
    """
    reset_clock()
    case = create_triaged_case(title="RBAC1", allegation_category="FRAUD",
                               severity="HIGH", department="Finance")
    plan = get_success_data(api.create_plan(
        case["id"], create_plan_payload(expected_case_version=case["version"]), INV
    ))
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_plan(plan["id"], {"to_status": "SUBMITTED"}, inv1))
    resp = api.transition_plan(plan["id"], {"to_status": "APPROVED"}, IC)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    after = get_success_data(api.get_plan(plan["id"], INV))
    assert after["status"] == "SUBMITTED"


def test_investigator_cannot_designate_privilege(api):
    """PRD §3.6: "`GeneralCounsel` designates privilege over an artifact of
    the case..."
    PRD §4 endpoint table restricts POST /api/cases/{id}/privilege-designations
    to `GeneralCounsel`.

    Design: Corner/rbac/investigator_cannot_designate_privilege
    """
    reset_clock()
    case = create_case(title="RBAC2", allegation_category="FRAUD",
                       severity="HIGH", department="Finance")
    resp = api.create_privilege_designation(
        case["id"],
        {"target_type": "INTERVIEW",
         "target_id": "00000000-0000-0000-0000-000000000001",
         "privilege_type": "ACP"},
        INV,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_hr_business_partner_cannot_run_pattern_scan(api):
    """PRD §3.15: "`ComplianceAuditor` runs a cross-case pattern scan over a
    rolling window."
    PRD §4 endpoint table restricts POST /api/pattern-alerts/scan to
    `ComplianceAuditor`.

    Design: Corner/rbac/hr_business_partner_cannot_run_pattern_scan
    """
    reset_clock()
    resp = api.scan_pattern_alerts({}, HR)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_system_admin_cannot_read_business_resources(api):
    """PRD §4 endpoint table excludes SystemAdmin from every business GET;
    SystemAdmin's only declared operation is POST /api/_clock/set_current_utc.
    PRD §2.1: "If the role is recognized but is not listed in the endpoint's
    authorized role set, the request is rejected with `ERR_UNAUTHORIZED_ROLE`
    (HTTP 403)."

    Design: Corner/rbac/system_admin_cannot_read_business_resources
    """
    reset_clock()
    resp = api.list_cases(ADMIN)
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)


def test_gc_cannot_decide_disclosure_clo_exclusive(api):
    """PRD §3.11: "Decision is made by the `ChiefLegalOfficer` and moves
    `PENDING` to `DECIDED`."
    PRD §4 endpoint table grants POST
    /api/self-disclosure-decisions/{id}/transition to `ChiefLegalOfficer,
    GeneralCounsel`, but §3.11 actor-restricts the DECIDED transition to
    ChiefLegalOfficer; §2.8 step 6 makes a per-transition actor restriction
    surface as `ERR_UNAUTHORIZED_ROLE`.

    Design: Corner/rbac/gc_cannot_decide_disclosure_clo_exclusive
    """
    reset_clock()
    bundle = create_case_in_fieldwork(
        title="RBAC5", allegation_category="BRIBERY", severity="CRITICAL",
        department="Sales",
    )
    case = bundle["case"]
    inv1 = make_investigator_headers(TEST_DEFAULTS["DRAFTER_ID"])
    get_success_data(api.transition_case(case["id"], {"to_status": "FINDINGS"}, inv1))
    case_fresh = get_success_data(api.get_case(case["id"], GC))
    d1 = get_success_data(api.create_self_disclosure_decision(
        case["id"],
        create_disclosure_payload(expected_case_version=case_fresh["version"]),
        GC,
    ))
    resp = api.transition_self_disclosure_decision(
        d1["id"],
        {"to_status": "DECIDED", "decision": "DISCLOSE", "rationale": "r"},
        GC,
    )
    validate_error(resp, ApiErrorId.ERR_UNAUTHORIZED_ROLE, expected_status=403)
    after = get_success_data(api.get_self_disclosure_decision(d1["id"], GC))
    assert after["status"] == "PENDING"
