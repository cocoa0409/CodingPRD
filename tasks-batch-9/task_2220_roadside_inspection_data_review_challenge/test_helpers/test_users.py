"""Auth header builders (PRD 2.1).

Every request carries `X-User-Role` and `X-User-ID`.  For the two carrier-side
roles the `X-User-ID` header *is* the acting carrier's id, so their headers can
only be built once the carrier exists — use `make_carrier_analyst_headers()` /
`make_carrier_safety_manager_headers()` with the created carrier's id.

For the three federal / state roles the id is an opaque string; several distinct
auditor ids are provided because segregation of duties (PRD 2.11) requires
different users for the fitness determination, the two CAP review branches and
the CAP decision.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .types import Role

# Opaque identities (PRD 2.1: "For the three agency roles the header is an
# opaque actor identifier").
STATE_OFFICER_ID = "officer_ohio_1"
STATE_OFFICER_ID_2 = "officer_ohio_2"
STATE_OFFICER_WA_ID = "officer_wash_1"
REVIEW_OFFICER_ID = "review_officer_1"
REVIEW_OFFICER_ID_2 = "review_officer_2"
AUDITOR_ALICE = "auditor_alice"
AUDITOR_BOB = "auditor_bob"
AUDITOR_CAROL = "auditor_carol"
AUDITOR_DAVE = "auditor_dave"


def make_carrier_analyst_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a CarrierAnalyst acting for `carrier_id`."""
    return build_user_headers(carrier_id, Role.CARRIER_ANALYST)


def make_carrier_safety_manager_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a CarrierSafetyManager acting for `carrier_id`."""
    return build_user_headers(carrier_id, Role.CARRIER_SAFETY_MANAGER)


def make_state_officer_headers(user_id: str = STATE_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.STATE_INSPECTION_OFFICER)


def make_review_officer_headers(user_id: str = REVIEW_OFFICER_ID) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FMCSA_REVIEW_OFFICER)


def make_auditor_headers(user_id: str = AUDITOR_ALICE) -> Dict[str, str]:
    return build_user_headers(user_id, Role.FMCSA_PROGRAM_AUDITOR)


#: Ready-made headers for the roles whose identity is opaque.
TEST_USERS = {
    "state_officer": make_state_officer_headers(STATE_OFFICER_ID),
    "state_officer_2": make_state_officer_headers(STATE_OFFICER_ID_2),
    "state_officer_wa": make_state_officer_headers(STATE_OFFICER_WA_ID),
    "review_officer": make_review_officer_headers(REVIEW_OFFICER_ID),
    "review_officer_2": make_review_officer_headers(REVIEW_OFFICER_ID_2),
    "auditor_alice": make_auditor_headers(AUDITOR_ALICE),
    "auditor_bob": make_auditor_headers(AUDITOR_BOB),
    "auditor_carol": make_auditor_headers(AUDITOR_CAROL),
    "auditor_dave": make_auditor_headers(AUDITOR_DAVE),
}
