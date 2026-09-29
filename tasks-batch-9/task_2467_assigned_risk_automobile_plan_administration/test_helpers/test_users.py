"""Pre-built role headers for every role in the PRD.

Authentication is carried by the ``X-User-ID`` and ``X-User-Role`` headers.

``TEST_USERS`` holds shared constants — safe for the two opaque roles
(``PlanAdministrator``, ``ComplianceExaminer``) and for tests whose success does
not depend on the caller owning the subject resource.

``ServicingCarrier`` and ``ProducerAgent`` are identity-bearing roles: the
``X-User-ID`` of a ``ServicingCarrier`` is the ``id`` of the carrier it acts as,
and the ``X-User-ID`` of a ``ProducerAgent`` is the ``id`` of the producer it
acts as. Any ownership-gated call MUST therefore be made with the matching
``make_*_headers(entity_id)`` builder, never with the shared constant.
"""
from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# Stable identifiers for the two opaque roles. The plan compares examiner
# identities to each other (segregation of duties), so two examiners are needed.
PLAN_ADMINISTRATOR_USER_ID = "ADMIN-1"
EXAMINER_ONE_USER_ID = "EX-1"
EXAMINER_TWO_USER_ID = "EX-2"

TEST_USERS: Dict[str, Dict[str, str]] = {
    "plan_administrator_headers": build_user_headers(PLAN_ADMINISTRATOR_USER_ID, "PlanAdministrator"),
    "compliance_examiner_headers": build_user_headers(EXAMINER_ONE_USER_ID, "ComplianceExaminer"),
    "second_compliance_examiner_headers": build_user_headers(EXAMINER_TWO_USER_ID, "ComplianceExaminer"),
    # Fallback constants for the identity-bearing roles: use only where the call
    # under test is not ownership-gated (bad payloads, unknown identifiers).
    "servicing_carrier_headers": build_user_headers("test-carrier-1", "ServicingCarrier"),
    "producer_agent_headers": build_user_headers("test-producer-1", "ProducerAgent"),
}


def make_plan_administrator_headers(user_id: str = PLAN_ADMINISTRATOR_USER_ID) -> Dict[str, str]:
    """Headers for a PlanAdministrator caller."""
    return build_user_headers(user_id, "PlanAdministrator")


def make_compliance_examiner_headers(user_id: str = EXAMINER_ONE_USER_ID) -> Dict[str, str]:
    """Headers for a ComplianceExaminer caller. The identifier is recorded on
    findings and compared on resolution, so pass distinct values to model two
    different examiners."""
    return build_user_headers(user_id, "ComplianceExaminer")


def make_servicing_carrier_headers(carrier_id: str) -> Dict[str, str]:
    """Headers for a ServicingCarrier caller. ``carrier_id`` must be the real
    ``Carrier.id`` the caller acts as — every carrier write is scoped to it."""
    return build_user_headers(carrier_id, "ServicingCarrier")


def make_producer_agent_headers(producer_id: str) -> Dict[str, str]:
    """Headers for a ProducerAgent caller. ``producer_id`` must be the real
    ``Producer.id`` the caller acts as — every producer write is scoped to it."""
    return build_user_headers(producer_id, "ProducerAgent")


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Escape hatch for tests that need an arbitrary identity/role pairing."""
    return build_user_headers(user_id, role)
