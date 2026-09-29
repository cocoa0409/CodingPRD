"""Shared test identities.

Five of the six roles carry an opaque `X-User-ID` that the server never compares
to an entity `id`, so a module-level constant is correct for them. The sixth role
is different: for a `ParticipantAdmin` the `X-User-ID` *is* the id of the acting
participant, so admin headers must always be built per participant with
`make_participant_admin_headers`.
"""

from prd_bench_local_runner.testing import build_user_headers

from .types import Headers

ROLE_NETWORK_OPERATOR = "NetworkOperator"
ROLE_PARTICIPANT_ADMIN = "ParticipantAdmin"
ROLE_LIQUIDITY_OFFICER = "LiquidityOfficer"
ROLE_PAYMENT_OPERATOR = "PaymentOperator"
ROLE_FRAUD_REVIEWER = "FraudReviewer"
ROLE_CORE_BANKING_SYSTEM = "CoreBankingSystem"

ALL_ROLES = (
    ROLE_NETWORK_OPERATOR,
    ROLE_PARTICIPANT_ADMIN,
    ROLE_LIQUIDITY_OFFICER,
    ROLE_PAYMENT_OPERATOR,
    ROLE_FRAUD_REVIEWER,
    ROLE_CORE_BANKING_SYSTEM,
)

# -------------------------------------------------------------------- user ids
USER_NETOPS = "netops-01"
USER_LIQ_ONE = "liq-01"
USER_LIQ_TWO = "liq-02"
USER_OPS_ALPHA = "ops-alpha-01"
USER_OPS_BETA = "ops-beta-01"
USER_OPS_GAMMA = "ops-gamma-01"
USER_OPS_DELTA = "ops-delta-01"
USER_REVIEWER_ONE = "reviewer-01"
USER_REVIEWER_TWO = "reviewer-02"
USER_CORE_ALPHA = "core-alpha-01"
USER_CORE_BETA = "core-beta-01"
USER_DUAL_HAT = "dual-hat-01"
USER_INTERN = "intern-01"

# -------------------------------------------------------------- header bundles
NETWORK_OPERATOR: Headers = build_user_headers(USER_NETOPS, ROLE_NETWORK_OPERATOR)
LIQUIDITY_OFFICER: Headers = build_user_headers(USER_LIQ_ONE, ROLE_LIQUIDITY_OFFICER)
LIQUIDITY_OFFICER_TWO: Headers = build_user_headers(USER_LIQ_TWO, ROLE_LIQUIDITY_OFFICER)
PAYMENT_OPERATOR_ALPHA: Headers = build_user_headers(USER_OPS_ALPHA, ROLE_PAYMENT_OPERATOR)
PAYMENT_OPERATOR_BETA: Headers = build_user_headers(USER_OPS_BETA, ROLE_PAYMENT_OPERATOR)
PAYMENT_OPERATOR_GAMMA: Headers = build_user_headers(USER_OPS_GAMMA, ROLE_PAYMENT_OPERATOR)
PAYMENT_OPERATOR_DELTA: Headers = build_user_headers(USER_OPS_DELTA, ROLE_PAYMENT_OPERATOR)
FRAUD_REVIEWER: Headers = build_user_headers(USER_REVIEWER_ONE, ROLE_FRAUD_REVIEWER)
FRAUD_REVIEWER_TWO: Headers = build_user_headers(USER_REVIEWER_TWO, ROLE_FRAUD_REVIEWER)
CORE_BANKING_SYSTEM: Headers = build_user_headers(USER_CORE_ALPHA, ROLE_CORE_BANKING_SYSTEM)
CORE_BANKING_SYSTEM_BETA: Headers = build_user_headers(USER_CORE_BETA, ROLE_CORE_BANKING_SYSTEM)

# One operator identity that wears two hats: it originates transfers as a
# PaymentOperator and then tries to review them as a FraudReviewer.
DUAL_HAT_OPERATOR: Headers = build_user_headers(USER_DUAL_HAT, ROLE_PAYMENT_OPERATOR)
DUAL_HAT_REVIEWER: Headers = build_user_headers(USER_DUAL_HAT, ROLE_FRAUD_REVIEWER)

# A role name that is not one of the six declared roles.
UNDECLARED_ROLE: Headers = build_user_headers(USER_INTERN, "TreasuryIntern")

# Malformed identity headers.
MISSING_USER_ID: Headers = {"X-User-Role": ROLE_NETWORK_OPERATOR, "Content-Type": "application/json"}
MISSING_ROLE: Headers = {"X-User-ID": USER_NETOPS, "Content-Type": "application/json"}
EMPTY_USER_ID: Headers = build_user_headers("", ROLE_NETWORK_OPERATOR)
EMPTY_ROLE: Headers = build_user_headers(USER_NETOPS, "")
NO_HEADERS: Headers = {"Content-Type": "application/json"}


def make_participant_admin_headers(participant_id: str) -> Headers:
    """Build `ParticipantAdmin` headers for one specific participant.

    A `ParticipantAdmin`'s `X-User-ID` is the `id` of the acting participant, and
    ownership checks compare a resource's participant reference against it, so
    there is no such thing as a shared administrator identity.
    """
    return build_user_headers(participant_id, ROLE_PARTICIPANT_ADMIN)


def make_payment_operator_headers(user_id: str) -> Headers:
    """Build `PaymentOperator` headers for an arbitrary opaque operator id."""
    return build_user_headers(user_id, ROLE_PAYMENT_OPERATOR)


def make_liquidity_officer_headers(user_id: str) -> Headers:
    """Build `LiquidityOfficer` headers for an arbitrary opaque officer id."""
    return build_user_headers(user_id, ROLE_LIQUIDITY_OFFICER)


def make_fraud_reviewer_headers(user_id: str) -> Headers:
    """Build `FraudReviewer` headers for an arbitrary opaque analyst id."""
    return build_user_headers(user_id, ROLE_FRAUD_REVIEWER)
