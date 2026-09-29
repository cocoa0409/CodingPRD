"""Header builders for the five roles (PRD §2.1).

The four operator roles carry opaque identity, so their `X-User-ID` values are
fixed strings. The `Insured` role is account-bound: `X-User-ID` is the `id` of
the acting insured account, so insured headers must always be built from a
concrete account id via `make_insured_headers`.
"""
from prd_bench_local_runner.testing import build_user_headers

from .types import UserRole

# Opaque operator identifiers. Two distinct ids exist for the Underwriter and
# the ClaimsAdjuster roles so that segregation of duties (PRD §2.11) can be
# satisfied or deliberately violated.
UNDERWRITER_1 = "u-underwriter-1"
UNDERWRITER_2 = "u-underwriter-2"
ADJUSTER_1 = "u-adjuster-1"
ADJUSTER_2 = "u-adjuster-2"
PANEL_ADMIN_1 = "u-panel-1"
ACTUARY_1 = "u-actuary-1"


def underwriter_headers(user_id=UNDERWRITER_1):
    return build_user_headers(user_id, UserRole.UNDERWRITER.value)


def adjuster_headers(user_id=ADJUSTER_1):
    return build_user_headers(user_id, UserRole.CLAIMS_ADJUSTER.value)


def panel_admin_headers(user_id=PANEL_ADMIN_1):
    return build_user_headers(user_id, UserRole.PANEL_ADMIN.value)


def actuary_headers(user_id=ACTUARY_1):
    return build_user_headers(user_id, UserRole.PORTFOLIO_ACTUARY.value)


def make_insured_headers(insured_account_id):
    """Headers for the policyholder that owns `insured_account_id`."""
    return build_user_headers(insured_account_id, UserRole.INSURED.value)


# Pre-built header sets for the operator roles.
UNDERWRITER_HEADERS = underwriter_headers(UNDERWRITER_1)
UNDERWRITER_2_HEADERS = underwriter_headers(UNDERWRITER_2)
ADJUSTER_HEADERS = adjuster_headers(ADJUSTER_1)
ADJUSTER_2_HEADERS = adjuster_headers(ADJUSTER_2)
PANEL_ADMIN_HEADERS = panel_admin_headers(PANEL_ADMIN_1)
ACTUARY_HEADERS = actuary_headers(ACTUARY_1)

# Every role keyed by its wire spelling, for parametrised role sweeps.
ROLE_HEADERS = {
    UserRole.UNDERWRITER.value: UNDERWRITER_HEADERS,
    UserRole.CLAIMS_ADJUSTER.value: ADJUSTER_HEADERS,
    UserRole.PORTFOLIO_ACTUARY.value: ACTUARY_HEADERS,
    UserRole.PANEL_ADMIN.value: PANEL_ADMIN_HEADERS,
}

OPERATOR_ROLES = list(ROLE_HEADERS.keys())
