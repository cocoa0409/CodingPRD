"""Segregation-of-duties RBAC: role-exclusive operations, entity-backed
ownership, authentication, and shared GET access (PRD §2.1, §2.9).

Queue B / Corner — section `rbac`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_employer, create_pending_pwd, create_issued_pwd, create_lca,
    create_cap_program, get_employer_version, make_employer_agent_headers,
    role_only_headers, pwd_payload, perm_case_payload,
)

DOL = TEST_USERS["dol_analyst_headers"]
USCIS = TEST_USERS["uscis_officer_headers"]
AUDITOR = TEST_USERS["compliance_auditor_headers"]
EMPLOYER = TEST_USERS["employer_agent_headers"]


def test_dol_exclusive_pwd_issue_denied_to_employer(api):
    """PRD §3.2: "Only a `DOLAnalyst` may issue a determination, advancing it from
    `PENDING` to `ISSUED`."
    PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/dol_exclusive_pwd_issue_denied_to_employer
    """
    emp = create_employer()
    pwd = create_pending_pwd(emp["id"])
    version = get_employer_version(emp["id"])
    res = api.transition_pwd(pwd["id"], {"to_status": "ISSUED", "expected_employer_version": version},
                             make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_uscis_exclusive_create_cap_program_denied_to_employer(api):
    """PRD §3.5: "Each H-1B fiscal year is represented by a `CapProgram`, created
    by a `USCISOfficer`".
    PRD §2.1: "When the headers are valid but the role is not permitted to perform
    the requested operation, the request is rejected with `ERR_UNAUTHORIZED`
    (HTTP 403)."

    Design: Corner/rbac/uscis_exclusive_create_cap_program_denied_to_employer
    """
    emp = create_employer()
    res = api.create_cap_program({"fiscal_year": 2027, "selection_quota": 5},
                                 make_employer_agent_headers(emp["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_compliance_exclusive_audit_paf_denied_to_dol(api):
    """PRD §3.4: "Public-access-file compliance is audited by a
    `ComplianceAuditor`, the only role permitted to run a PAF audit on an
    application."

    Design: Corner/rbac/compliance_exclusive_audit_paf_denied_to_dol
    """
    emp = create_employer()
    lca = create_lca(emp["id"])
    res = api.audit_paf(lca["id"], DOL)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_employer_exclusive_create_perm_case_denied_to_dol(api):
    """PRD §2.9: "the acting role is permitted for the operation, and an
    `EmployerAgent` owns the target employer's resources; otherwise
    `ERR_UNAUTHORIZED` (403)."

    Design: Corner/rbac/employer_exclusive_create_perm_case_denied_to_dol
    """
    emp = create_employer()
    pwd = create_issued_pwd(emp["id"])
    res = api.create_perm_case(perm_case_payload(emp["id"], pwd["id"]), DOL)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_dol_exclusive_certify_lca_denied_to_employer(api):
    """PRD §3.4: "Only a `DOLAnalyst` may certify, moving the application from
    `DRAFT` to `CERTIFIED`."

    Design: Corner/rbac/dol_exclusive_certify_lca_denied_to_employer
    """
    emp = create_employer()
    lca = create_lca(emp["id"])
    hdr = make_employer_agent_headers(emp["id"])
    res = api.transition_lca(lca["id"], {"to_status": "CERTIFIED"}, hdr)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)
    assert validate_success(api.get_lca(lca["id"], hdr), 200)["status"] == "DRAFT"


def test_uscis_exclusive_run_lottery_denied_to_dol(api):
    """PRD §3.5: "The lottery itself is run by a `USCISOfficer` and, despite the
    name, is fully deterministic rather than random."

    Design: Corner/rbac/uscis_exclusive_run_lottery_denied_to_dol
    """
    cap = create_cap_program(2027, 5)
    res = api.run_lottery(cap["id"], DOL)
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_employer_cannot_act_on_other_employers_resource(api):
    """PRD §2.1: "an `EmployerAgent` may only create, transition, or otherwise
    mutate resources whose `employer_id` equals its own employer id, and an
    attempt to act on another employer's resource is rejected with
    `ERR_UNAUTHORIZED`."

    Design: Corner/rbac/employer_cannot_act_on_other_employers_resource
    """
    emp_a = create_employer(legal_name="Owner A")
    emp_b = create_employer(legal_name="Owner B")
    res = api.create_pwd(pwd_payload(emp_a["id"]), make_employer_agent_headers(emp_b["id"]))
    validate_error(res, ApiErrorId.ERR_UNAUTHORIZED, expected_status=403)


def test_missing_x_user_id_header_unauthenticated(api):
    """PRD §2.1: "Every request must carry two headers: `X-User-ID`, identifying
    the acting user, and `X-User-Role`, naming their operational capacity. If
    either header is missing, or if `X-User-Role` is not one of the recognized
    roles, the request is rejected with `ERR_UNAUTHENTICATED` (HTTP 401)."

    Design: Corner/rbac/missing_x_user_id_header_unauthenticated
    """
    emp = create_employer()
    res = api.get_employer(emp["id"], role_only_headers("EmployerAgent"))
    validate_error(res, ApiErrorId.ERR_UNAUTHENTICATED, expected_status=401)


def test_shared_get_allowed_for_all_roles(api):
    """PRD §2.1: "Every `GET` endpoint and the logical-clock control endpoint are
    available to all four roles."

    Design: Corner/rbac/shared_get_allowed_for_all_roles
    """
    emp = create_employer(legal_name="SharedGet Co")
    dol_view = validate_success(api.get_employer(emp["id"], DOL), 200)
    auditor_view = validate_success(api.get_employer(emp["id"], AUDITOR), 200)
    assert dol_view["legal_name"] == "SharedGet Co"
    assert auditor_view["legal_name"] == "SharedGet Co"
