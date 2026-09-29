"""Pre-built role headers for every committee role named by the PRD.

Six of the seven roles are backed by a persisted clinician record, so their
`X-User-ID` must be the acting `Clinician`'s own `id`. For those roles the
per-instance builders below are the only correct way to authenticate an
ownership-gated or identity-bound call. The shared `TEST_USERS` constants are
safe only for `SystemAdmin` (whose principal is an opaque operator identifier)
and for calls whose expected outcome does not depend on the caller matching a
stored clinician reference.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

# The literal principal accepted for the SystemAdmin-only endpoints.
SYSTEM_ADMIN_PRINCIPAL = "SYSTEM_ADMIN"

TEST_USERS: Dict[str, Dict[str, str]] = {
    # Opaque role — the shared constant is the canonical form.
    "system_admin_headers": build_user_headers(SYSTEM_ADMIN_PRINCIPAL, "SystemAdmin"),
    # Clinician-backed roles — fallbacks for tests that never reach an
    # identity comparison (for example an unknown-identifier 401 probe).
    "clinical_sponsor_headers": build_user_headers("test-sponsor-1", "ClinicalSponsor"),
    "informatics_builder_headers": build_user_headers("test-builder-1", "InformaticsBuilder"),
    "peer_reviewer_headers": build_user_headers("test-peer-1", "PeerReviewer"),
    "specialty_approver_headers": build_user_headers("test-specialty-1", "SpecialtyApprover"),
    "committee_chair_headers": build_user_headers("test-chair-1", "CommitteeChair"),
    "pharmacy_informaticist_headers": build_user_headers(
        "test-pharmacist-1", "PharmacyInformaticist"
    ),
}


def make_system_admin_headers(user_id: str = SYSTEM_ADMIN_PRINCIPAL) -> Dict[str, str]:
    """SystemAdmin acts under an opaque operator identifier."""
    return build_user_headers(user_id, "SystemAdmin")


def make_clinical_sponsor_headers(clinician_id: str) -> Dict[str, str]:
    """Pass the acting Clinician's own id."""
    return build_user_headers(clinician_id, "ClinicalSponsor")


def make_informatics_builder_headers(clinician_id: str) -> Dict[str, str]:
    """Pass the acting Clinician's own id."""
    return build_user_headers(clinician_id, "InformaticsBuilder")


def make_peer_reviewer_headers(clinician_id: str) -> Dict[str, str]:
    """Pass the acting Clinician's own id."""
    return build_user_headers(clinician_id, "PeerReviewer")


def make_specialty_approver_headers(clinician_id: str) -> Dict[str, str]:
    """Pass the acting Clinician's own id."""
    return build_user_headers(clinician_id, "SpecialtyApprover")


def make_committee_chair_headers(clinician_id: str) -> Dict[str, str]:
    """Pass the acting Clinician's own id."""
    return build_user_headers(clinician_id, "CommitteeChair")


def make_pharmacy_informaticist_headers(clinician_id: str) -> Dict[str, str]:
    """Pass the acting Clinician's own id."""
    return build_user_headers(clinician_id, "PharmacyInformaticist")


ROLE_HEADER_BUILDERS = {
    "ClinicalSponsor": make_clinical_sponsor_headers,
    "InformaticsBuilder": make_informatics_builder_headers,
    "PeerReviewer": make_peer_reviewer_headers,
    "SpecialtyApprover": make_specialty_approver_headers,
    "CommitteeChair": make_committee_chair_headers,
    "PharmacyInformaticist": make_pharmacy_informaticist_headers,
    "SystemAdmin": make_system_admin_headers,
}


def make_headers(role: str, user_id: str) -> Dict[str, str]:
    """Build headers for any role, using the clinician id where required."""
    return ROLE_HEADER_BUILDERS[role](user_id)
