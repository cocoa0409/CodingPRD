"""Pre-built role headers for every role in the PRD (§2.1)."""
from prd_bench_local_runner.testing import build_user_headers

# Shared constants — safe for opaque roles, and for tests that don't exercise ownership.
TEST_USERS = {
    "ip_counsel_headers": build_user_headers("counsel_1", "IPCounsel"),
    "ip_counsel_2_headers": build_user_headers("counsel_2", "IPCounsel"),
    "senior_counsel_headers": build_user_headers("senior_1", "SeniorCounsel"),
    "hr_partner_headers": build_user_headers("hr_1", "HRPartner"),
    "security_officer_headers": build_user_headers("sec_officer_1", "SecurityOfficer"),
    "security_officer_2_headers": build_user_headers("sec_officer_2", "SecurityOfficer"),
    # entity_backed roles: shared constants are fallbacks for non-ownership tests only.
    "employee_headers": build_user_headers("test-employee-1", "Employee"),
    "counterparty_rep_headers": build_user_headers("test-counterparty-1", "CounterpartyRep"),
}


# Per-instance builders — required for every entity_backed role.
def make_employee_headers(user_id: str) -> dict:
    """For Employee (entity_backed:Employee). Pass the actual Employee.id as user_id
    whenever the call is ownership-gated (sign own ack, complete own training,
    request own grant, submit/withdraw own disclosure)."""
    return build_user_headers(user_id, "Employee")


def make_counterparty_rep_headers(counterparty_id: str) -> dict:
    """For CounterpartyRep (entity_backed:Counterparty). Pass the actual
    Counterparty.id as user_id whenever the call is ownership-gated (execute own
    NDA, fulfill own obligation)."""
    return build_user_headers(counterparty_id, "CounterpartyRep")


def make_ip_counsel_headers(user_id: str) -> dict:
    """IPCounsel with a specific opaque operator id (for segregation-of-duties tests)."""
    return build_user_headers(user_id, "IPCounsel")


def make_senior_counsel_headers(user_id: str) -> dict:
    """SeniorCounsel with a specific opaque operator id (for segregation-of-duties tests)."""
    return build_user_headers(user_id, "SeniorCounsel")


def make_security_officer_headers(user_id: str) -> dict:
    """SecurityOfficer with a specific opaque operator id (for segregation-of-duties tests)."""
    return build_user_headers(user_id, "SecurityOfficer")
