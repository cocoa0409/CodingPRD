"""Pre-built role headers for every role in the PRD (§2.1).

All four roles use opaque identity — X-User-ID is an opaque operator identifier
never compared to any entity's id. Therefore only shared-constant header entries
are needed (no entity_backed per-instance builders).

The canonical operator identifiers used by composite fixtures are:
  LoanOfficer -> "officer-1", CreditApprover -> "approver-1".
The four-eyes separation rule (PRD §3.5) compares CreditApprover.X-User-ID against
the credit memo's authored_by_user_id, so the approver id must differ from the
authoring officer id; "approver-1" != "officer-1" keeps that guard satisfied.
"""
from prd_bench_local_runner.testing import build_user_headers


# Canonical operator identifiers (must stay distinct for the four-eyes rule).
OFFICER_USER_ID = "officer-1"
APPROVER_USER_ID = "approver-1"

TEST_USERS = {
    "loan_officer_headers": build_user_headers(OFFICER_USER_ID, "LoanOfficer"),
    "credit_approver_headers": build_user_headers(APPROVER_USER_ID, "CreditApprover"),
    "sba_officer_headers": build_user_headers("sba-1", "SbaOfficer"),
    "investor_servicer_headers": build_user_headers("inv-1", "InvestorServicer"),
}
