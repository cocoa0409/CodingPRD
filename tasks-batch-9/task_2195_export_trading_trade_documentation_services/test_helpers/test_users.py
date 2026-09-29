"""Pre-built auth headers.

``X-User-ID`` and ``X-User-Role`` are required on every request. The identity of a
``ForeignBuyer`` caller is the ForeignBuyer row id itself, so buyer headers must
always be built per-row with :func:`make_buyer_headers`.

Distinct owners get distinct user ids on purpose: the user who captured a credit
may not review it, and the user who generated a document may not examine the
presentation carrying it.
"""

from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Named identities. Every role that participates in a segregation-of-duties pair
# has at least two distinct ids so tests never have to reuse one.
USER_IDS: Dict[str, str] = {
    "ops_alice": "u_ops_alice",
    "ops_dana": "u_ops_dana",
    "ops_1": "ops_1",
    "ops_2": "ops_2",
    "comp_carl": "u_comp_carl",
    "tco_1": "tco_1",
    "rev_bob": "u_rev_bob",
    "rev_erin": "u_rev_erin",
    "rev_1": "rev_1",
    "fin_frank": "u_fin_frank",
    "fin_1": "fin_1",
    "admin_zoe": "u_admin_zoe",
    "admin_pat": "u_admin_pat",
    "adm_1": "adm_1",
    "dual_dana": "u_dual_dana",
    "ghost_gary": "u_ghost_gary",
}


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Pair an arbitrary user id with an arbitrary role."""
    return build_user_headers(user_id, role)


# --- ExportOpsCoordinator ----------------------------------------------------
OPS_ALICE = make_headers(USER_IDS["ops_alice"], Role.EXPORT_OPS_COORDINATOR.value)
OPS_DANA = make_headers(USER_IDS["ops_dana"], Role.EXPORT_OPS_COORDINATOR.value)
OPS_1 = make_headers(USER_IDS["ops_1"], Role.EXPORT_OPS_COORDINATOR.value)
OPS_2 = make_headers(USER_IDS["ops_2"], Role.EXPORT_OPS_COORDINATOR.value)

# --- TradeComplianceOfficer --------------------------------------------------
COMPLIANCE_CARL = make_headers(
    USER_IDS["comp_carl"], Role.TRADE_COMPLIANCE_OFFICER.value
)
TCO_1 = make_headers(USER_IDS["tco_1"], Role.TRADE_COMPLIANCE_OFFICER.value)

# --- DocumentaryCreditReviewer ----------------------------------------------
REVIEWER_BOB = make_headers(
    USER_IDS["rev_bob"], Role.DOCUMENTARY_CREDIT_REVIEWER.value
)
REVIEWER_ERIN = make_headers(
    USER_IDS["rev_erin"], Role.DOCUMENTARY_CREDIT_REVIEWER.value
)
REV_1 = make_headers(USER_IDS["rev_1"], Role.DOCUMENTARY_CREDIT_REVIEWER.value)

# --- FinanceCollectionsOfficer ----------------------------------------------
FINANCE_FRANK = make_headers(
    USER_IDS["fin_frank"], Role.FINANCE_COLLECTIONS_OFFICER.value
)
FIN_1 = make_headers(USER_IDS["fin_1"], Role.FINANCE_COLLECTIONS_OFFICER.value)

# --- PlatformAdmin -----------------------------------------------------------
ADMIN_ZOE = make_headers(USER_IDS["admin_zoe"], Role.PLATFORM_ADMIN.value)
ADMIN_PAT = make_headers(USER_IDS["admin_pat"], Role.PLATFORM_ADMIN.value)
ADM_1 = make_headers(USER_IDS["adm_1"], Role.PLATFORM_ADMIN.value)

# --- dual-hat subject --------------------------------------------------------
# The same person wearing two hats: used to prove that segregation of duties is
# keyed on the recorded user id and not on the role presented on the request.
DUAL_DANA_AS_OPS = make_headers(
    USER_IDS["dual_dana"], Role.EXPORT_OPS_COORDINATOR.value
)
DUAL_DANA_AS_REVIEWER = make_headers(
    USER_IDS["dual_dana"], Role.DOCUMENTARY_CREDIT_REVIEWER.value
)


TEST_USERS: Dict[str, Dict[str, str]] = {
    "ops_alice": OPS_ALICE,
    "ops_dana": OPS_DANA,
    "ops_1": OPS_1,
    "ops_2": OPS_2,
    "compliance_carl": COMPLIANCE_CARL,
    "tco_1": TCO_1,
    "reviewer_bob": REVIEWER_BOB,
    "reviewer_erin": REVIEWER_ERIN,
    "rev_1": REV_1,
    "finance_frank": FINANCE_FRANK,
    "fin_1": FIN_1,
    "admin_zoe": ADMIN_ZOE,
    "admin_pat": ADMIN_PAT,
    "adm_1": ADM_1,
    "dual_dana_as_ops": DUAL_DANA_AS_OPS,
    "dual_dana_as_reviewer": DUAL_DANA_AS_REVIEWER,
}


def make_buyer_headers(buyer_id: str) -> Dict[str, str]:
    """Headers for a ForeignBuyer caller: the user id IS the ForeignBuyer row id."""
    return make_headers(buyer_id, Role.FOREIGN_BUYER.value)


def make_ops_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.EXPORT_OPS_COORDINATOR.value)


def make_reviewer_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.DOCUMENTARY_CREDIT_REVIEWER.value)


def make_compliance_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.TRADE_COMPLIANCE_OFFICER.value)


def make_finance_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.FINANCE_COLLECTIONS_OFFICER.value)


def make_admin_headers(user_id: str) -> Dict[str, str]:
    return make_headers(user_id, Role.PLATFORM_ADMIN.value)
