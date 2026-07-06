"""Optimistic concurrency on prevailing-wage issuance and immediate consistency
of the running wage obligation (PRD §2.6, §3.1, §3.2).

Queue B / Corner — sections `cross_cutting` and `consistency_model`.
"""
from test_helpers import (
    api_client, validate_success, validate_error, ApiErrorId, TEST_USERS,
    create_employer, create_pending_pwd, create_lca, certify_lca,
    make_employer_agent_headers,
)

DOL = TEST_USERS["dol_analyst_headers"]


def test_occ_stale_employer_version_on_pwd_issue_rejected(api):
    """PRD §2.6: "If `expected_employer_version` does not equal the parent
    `Employer`'s current `version`, the request is rejected with
    `ERR_STALE_VERSION` (HTTP 412) and nothing is mutated."

    Design: Corner/cross_cutting/occ_stale_employer_version_on_pwd_issue_rejected
    """
    emp = create_employer()
    stale_version = emp["version"]  # 1
    pwd_a = create_pending_pwd(emp["id"], area_code="AREA_A")
    pwd_b = create_pending_pwd(emp["id"], area_code="AREA_B")
    # Issue A with the fresh version; this advances Employer.version to 2.
    validate_success(api.transition_pwd(
        pwd_a["id"], {"to_status": "ISSUED", "expected_employer_version": stale_version}, DOL), 200)
    # Issue B carrying the now-stale version 1.
    res = api.transition_pwd(
        pwd_b["id"], {"to_status": "ISSUED", "expected_employer_version": stale_version}, DOL)
    validate_error(res, ApiErrorId.ERR_STALE_VERSION, expected_status=412)
    assert validate_success(api.get_pwd(pwd_b["id"], DOL), 200)["status"] == "PENDING"


def test_occ_current_employer_version_issues_and_increments_version(api):
    """PRD §3.2: "Finally, issuance increments the parent `Employer`'s `version` by
    one."
    PRD §2.6: "Issuing a prevailing-wage determination — the transition that moves
    it from `PENDING` to `ISSUED` — is guarded by optimistic concurrency against
    its parent `Employer`."

    Design: Corner/cross_cutting/occ_current_employer_version_issues_and_increments_version
    """
    emp = create_employer()
    pwd = create_pending_pwd(emp["id"])
    issued = validate_success(api.transition_pwd(
        pwd["id"], {"to_status": "ISSUED", "expected_employer_version": emp["version"]}, DOL), 200)
    assert issued["status"] == "ISSUED"
    emp_after = validate_success(api.get_employer(emp["id"], make_employer_agent_headers(emp["id"])), 200)
    assert emp_after["version"] == 2


def test_immediate_wage_obligation_visible_right_after_certify(api):
    """PRD §3.1: "certifying an application adds that application's locked
    `required_wage_cents`, and withdrawing a certified application subtracts the
    same amount."

    Design: Corner/consistency_model/immediate_wage_obligation_visible_right_after_certify
    """
    emp = create_employer()
    lca = create_lca(emp["id"], offered_wage_cents=12000000, prevailing_wage_cents=10000000)
    certify_lca(emp["id"], lca["id"])
    emp_after = validate_success(api.get_employer(emp["id"], make_employer_agent_headers(emp["id"])), 200)
    assert emp_after["total_wage_obligation_cents"] == 12000000
