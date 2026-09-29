"""Principal identities and the header builders that thread them into requests.

Four roles carry opaque operator identities (`CreditOfficer`, `TradeFinanceOfficer`,
`DocumentExaminer`, `ComplianceOfficer`) and `SystemOperator` is likewise opaque, so
their `X-User-ID` values are free-form strings. Three roles are entity-backed
(`ApplicantUser`, `BeneficiaryUser`, `CorrespondentBank`): for them `X-User-ID` must be
the primary key of the row the principal acts for, so those headers are built per
instance from an id captured at setup time.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# --- opaque operator identifiers ---
CREDIT_OFFICER_1 = "co_1"
CREDIT_OFFICER_2 = "co_2"
TRADE_FINANCE_OFFICER_1 = "tfo_1"
TRADE_FINANCE_OFFICER_2 = "tfo_2"
DOCUMENT_EXAMINER_1 = "dx_1"
DOCUMENT_EXAMINER_2 = "dx_2"
COMPLIANCE_OFFICER_1 = "cmp_1"
COMPLIANCE_OFFICER_2 = "cmp_2"
SYSTEM_OPERATOR_1 = "sysop_1"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "credit_officer_1": {"user_id": CREDIT_OFFICER_1, "role": Role.CREDIT_OFFICER.value},
    "credit_officer_2": {"user_id": CREDIT_OFFICER_2, "role": Role.CREDIT_OFFICER.value},
    "trade_finance_officer_1": {
        "user_id": TRADE_FINANCE_OFFICER_1,
        "role": Role.TRADE_FINANCE_OFFICER.value,
    },
    "trade_finance_officer_2": {
        "user_id": TRADE_FINANCE_OFFICER_2,
        "role": Role.TRADE_FINANCE_OFFICER.value,
    },
    "document_examiner_1": {
        "user_id": DOCUMENT_EXAMINER_1,
        "role": Role.DOCUMENT_EXAMINER.value,
    },
    "document_examiner_2": {
        "user_id": DOCUMENT_EXAMINER_2,
        "role": Role.DOCUMENT_EXAMINER.value,
    },
    "compliance_officer_1": {
        "user_id": COMPLIANCE_OFFICER_1,
        "role": Role.COMPLIANCE_OFFICER.value,
    },
    "compliance_officer_2": {
        "user_id": COMPLIANCE_OFFICER_2,
        "role": Role.COMPLIANCE_OFFICER.value,
    },
    "system_operator_1": {
        "user_id": SYSTEM_OPERATOR_1,
        "role": Role.SYSTEM_OPERATOR.value,
    },
}


# ----------------------------------------------------------------------
# Opaque-operator header builders
# ----------------------------------------------------------------------
def credit_officer_headers(user_id: str = CREDIT_OFFICER_1) -> Dict[str, str]:
    return build_user_headers(user_id, Role.CREDIT_OFFICER.value)


def trade_finance_officer_headers(
    user_id: str = TRADE_FINANCE_OFFICER_1,
) -> Dict[str, str]:
    return build_user_headers(user_id, Role.TRADE_FINANCE_OFFICER.value)


def document_examiner_headers(user_id: str = DOCUMENT_EXAMINER_1) -> Dict[str, str]:
    return build_user_headers(user_id, Role.DOCUMENT_EXAMINER.value)


def compliance_officer_headers(user_id: str = COMPLIANCE_OFFICER_1) -> Dict[str, str]:
    return build_user_headers(user_id, Role.COMPLIANCE_OFFICER.value)


def system_operator_headers(user_id: str = SYSTEM_OPERATOR_1) -> Dict[str, str]:
    return build_user_headers(user_id, Role.SYSTEM_OPERATOR.value)


# ----------------------------------------------------------------------
# Entity-backed header builders — the id IS the acting row's primary key
# ----------------------------------------------------------------------
def make_applicant_user_headers(applicant_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting Applicant."""
    return build_user_headers(applicant_id, Role.APPLICANT_USER.value)


def make_beneficiary_user_headers(beneficiary_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting Beneficiary."""
    return build_user_headers(beneficiary_id, Role.BENEFICIARY_USER.value)


def make_correspondent_bank_headers(bank_id: str) -> Dict[str, str]:
    """`X-User-ID` is the `id` of the acting Bank."""
    return build_user_headers(bank_id, Role.CORRESPONDENT_BANK.value)


def headers_for(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for an arbitrary role/id pair (used by authorization tests)."""
    return build_user_headers(user_id, role)
