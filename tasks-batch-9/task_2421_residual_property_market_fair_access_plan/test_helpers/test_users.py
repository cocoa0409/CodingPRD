"""Acting identities and header builders.

Two of the plan's rules make identity, not merely role, load-bearing:

* three roles are entity-backed, so ``X-User-ID`` must be the id of a real
  persisted row (a ``Producer``, a ``MemberInsurer`` or an ``Applicant``), and
* three segregation-of-duties separations are keyed on ``X-User-ID`` rather than
  on ``X-User-Role``, so the opaque operators come in numbered pairs.

``TEST_USERS`` holds the shared opaque operators.  The three ``make_*_headers``
builders exist because an entity-backed identity is only known once the row has
been created, so it can never be a module-level constant.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_INSPECTOR,
    ROLE_MEMBER_INSURER_USER,
    ROLE_PLAN_ADMIN,
    ROLE_POLICYHOLDER,
    ROLE_PRODUCER,
    ROLE_RATE_ANALYST,
    ROLE_REGULATOR,
    ROLE_UNDERWRITER,
)

# Opaque operator identifiers (PRD 2.1: "X-User-ID is an operator identifier
# not tied to any persisted entity").
ADMIN_USER_ID = "admin-1"
UNDERWRITER_ONE_ID = "uw-1"
UNDERWRITER_TWO_ID = "uw-2"
UNDERWRITER_THREE_ID = "uw-3"
INSPECTOR_ONE_ID = "insp-1"
INSPECTOR_TWO_ID = "insp-2"
RATE_ANALYST_ID = "ra-1"
RATE_ANALYST_TWO_ID = "ra-2"
REGULATOR_ID = "reg-1"
REGULATOR_TWO_ID = "reg-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "plan_admin": {"user_id": ADMIN_USER_ID, "role": ROLE_PLAN_ADMIN},
    # uw-1 reviews eligibility; uw-2 binds.  They must be different people or
    # the bind trips ERR_SEGREGATION_OF_DUTIES.
    "underwriter_reviewer": {"user_id": UNDERWRITER_ONE_ID, "role": ROLE_UNDERWRITER},
    "underwriter_binder": {"user_id": UNDERWRITER_TWO_ID, "role": ROLE_UNDERWRITER},
    "underwriter_third": {"user_id": UNDERWRITER_THREE_ID, "role": ROLE_UNDERWRITER},
    "inspector_primary": {"user_id": INSPECTOR_ONE_ID, "role": ROLE_INSPECTOR},
    "inspector_secondary": {"user_id": INSPECTOR_TWO_ID, "role": ROLE_INSPECTOR},
    "rate_analyst": {"user_id": RATE_ANALYST_ID, "role": ROLE_RATE_ANALYST},
    "rate_analyst_second": {"user_id": RATE_ANALYST_TWO_ID, "role": ROLE_RATE_ANALYST},
    # reg-1 reviews filings filed by ra-1; reg-2 exists for the mirror case.
    "regulator": {"user_id": REGULATOR_ID, "role": ROLE_REGULATOR},
    "regulator_second": {"user_id": REGULATOR_TWO_ID, "role": ROLE_REGULATOR},
}


def headers_for(key: str) -> Dict[str, str]:
    """Headers for one of the shared opaque operators in ``TEST_USERS``."""
    user = TEST_USERS[key]
    return build_user_headers(user["user_id"], user["role"])


# Convenience accessors for the shared operators.
def admin_headers() -> Dict[str, str]:
    return headers_for("plan_admin")


def reviewer_headers() -> Dict[str, str]:
    return headers_for("underwriter_reviewer")


def binder_headers() -> Dict[str, str]:
    return headers_for("underwriter_binder")


def third_underwriter_headers() -> Dict[str, str]:
    return headers_for("underwriter_third")


def inspector_headers() -> Dict[str, str]:
    return headers_for("inspector_primary")


def second_inspector_headers() -> Dict[str, str]:
    return headers_for("inspector_secondary")


def rate_analyst_headers() -> Dict[str, str]:
    return headers_for("rate_analyst")


def second_rate_analyst_headers() -> Dict[str, str]:
    return headers_for("rate_analyst_second")


def regulator_headers() -> Dict[str, str]:
    return headers_for("regulator")


def second_regulator_headers() -> Dict[str, str]:
    return headers_for("regulator_second")


# --- entity-backed identities ------------------------------------------------

def make_producer_headers(producer_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``Producer`` record."""
    return build_user_headers(producer_id, ROLE_PRODUCER)


def make_member_insurer_headers(member_insurer_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``MemberInsurer`` record."""
    return build_user_headers(member_insurer_id, ROLE_MEMBER_INSURER_USER)


def make_policyholder_headers(applicant_id: str) -> Dict[str, str]:
    """``X-User-ID`` is the id of the acting ``Applicant`` record."""
    return build_user_headers(applicant_id, ROLE_POLICYHOLDER)


def make_underwriter_headers(user_id: str) -> Dict[str, str]:
    """An arbitrary underwriter operator id, for segregation-of-duties cases."""
    return build_user_headers(user_id, ROLE_UNDERWRITER)


def make_inspector_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_INSPECTOR)


def make_rate_analyst_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_RATE_ANALYST)


def make_regulator_headers(user_id: str) -> Dict[str, str]:
    return build_user_headers(user_id, ROLE_REGULATOR)
