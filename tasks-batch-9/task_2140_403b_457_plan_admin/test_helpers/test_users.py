"""Pre-built role headers for every role in the PRD.

`SystemOperator` and `ComplianceOfficer` carry an opaque operator identifier
that the server never compares to any row's id, so a shared constant is the
canonical form for them. `PlanSponsorAdmin`, `VendorRepresentative` and
`Participant` are entity-backed: their `X-User-ID` must be the id of the acting
`Employer`, `Vendor` or `Participant`, so ownership-gated calls MUST use the
per-instance builders below.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import OFFICER_ONE, OFFICER_TWO

# Shared constants — safe for the opaque roles, and for calls that never touch
# an ownership check (bad-payload, missing-resource, role-refusal probes).
TEST_USERS: Dict[str, Dict[str, str]] = {
    "system_operator_headers": build_user_headers("ops-1", "SystemOperator"),
    "compliance_officer_headers": build_user_headers(OFFICER_ONE, "ComplianceOfficer"),
    "compliance_officer_two_headers": build_user_headers(OFFICER_TWO, "ComplianceOfficer"),
    # Entity-backed roles: fallbacks only, never for ownership-gated calls.
    "plan_sponsor_admin_headers": build_user_headers("test-sponsor-1", "PlanSponsorAdmin"),
    "vendor_representative_headers": build_user_headers("test-vendor-1", "VendorRepresentative"),
    "participant_headers": build_user_headers("test-participant-1", "Participant"),
}

# Headers carrying neither X-User-ID nor X-User-Role.
NO_AUTH_HEADERS: Dict[str, str] = {"Content-Type": "application/json"}


def make_sponsor_headers(employer_id: str) -> Dict[str, str]:
    """PlanSponsorAdmin acting for the Employer whose id is `employer_id`."""
    return build_user_headers(employer_id, "PlanSponsorAdmin")


def make_vendor_headers(vendor_id: str) -> Dict[str, str]:
    """VendorRepresentative acting for the Vendor whose id is `vendor_id`."""
    return build_user_headers(vendor_id, "VendorRepresentative")


def make_participant_headers(participant_id: str) -> Dict[str, str]:
    """Participant acting for themselves; pass the Participant's own id."""
    return build_user_headers(participant_id, "Participant")


def make_officer_headers(user_id: str = OFFICER_ONE) -> Dict[str, str]:
    """ComplianceOfficer with an explicit opaque operator identifier."""
    return build_user_headers(user_id, "ComplianceOfficer")


def make_operator_headers(user_id: str = "ops-1") -> Dict[str, str]:
    """SystemOperator with an explicit opaque operator identifier."""
    return build_user_headers(user_id, "SystemOperator")
