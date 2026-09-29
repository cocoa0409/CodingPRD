"""Pre-built role headers for the six roles the PRD recognises.

Four roles carry an opaque operator identifier that the server records but
never compares against a stored `id`: `RemedialProjectManager`,
`AllocationFacilitator`, `SettlementCounsel` and `CommunityMember`.

Two roles are entity-backed and their `X-User-ID` IS an entity identifier:
for `PRPRepresentative` it is the `id` of the acting potentially responsible
party, and for `Contractor` it is the `id` of the acting remediation contract.
Ownership-gated calls for those two roles must always be built from the real
entity id through `make_prp_representative_headers` /
`make_contractor_headers`; the shared entries below exist only for probes that
deliberately act with an unrelated identity.
"""
from prd_bench_local_runner.testing import build_user_headers

# Two segregation-of-duties rules compare one project-manager identifier
# against another, so the suite works with three distinct manager identities:
# rpm-001 authors, rpm-002 reviews and approves, rpm-003 signs.
AUTHOR_PM_ID = "rpm-001"
REVIEWER_PM_ID = "rpm-002"
SIGNER_PM_ID = "rpm-003"
FACILITATOR_ID = "af-001"
COUNSEL_ID = "sc-001"
COMMUNITY_ID = "cm-001"

TEST_USERS = {
    "author_pm_headers": build_user_headers(AUTHOR_PM_ID, "RemedialProjectManager"),
    "reviewer_pm_headers": build_user_headers(REVIEWER_PM_ID, "RemedialProjectManager"),
    "signer_pm_headers": build_user_headers(SIGNER_PM_ID, "RemedialProjectManager"),
    "facilitator_headers": build_user_headers(FACILITATOR_ID, "AllocationFacilitator"),
    "counsel_headers": build_user_headers(COUNSEL_ID, "SettlementCounsel"),
    "community_headers": build_user_headers(COMMUNITY_ID, "CommunityMember"),
    # Shared fallbacks only — never use either for an ownership-gated call.
    "prp_representative_headers": build_user_headers(
        "prp-representative-unbound", "PRPRepresentative"
    ),
    "contractor_headers": build_user_headers("contractor-unbound", "Contractor"),
}


def make_project_manager_headers(user_id: str) -> dict:
    """Headers for one project-manager identity.

    Pass a distinct identifier per hand: the author of an investigation may not
    review it, and the approver of an investigation may not sign the decision
    document that cites it.
    """
    return build_user_headers(user_id, "RemedialProjectManager")


def make_facilitator_headers(user_id: str = FACILITATOR_ID) -> dict:
    return build_user_headers(user_id, "AllocationFacilitator")


def make_counsel_headers(user_id: str = COUNSEL_ID) -> dict:
    return build_user_headers(user_id, "SettlementCounsel")


def make_community_headers(user_id: str = COMMUNITY_ID) -> dict:
    return build_user_headers(user_id, "CommunityMember")


def make_prp_representative_headers(prp_id: str) -> dict:
    """Headers for the representative of one party.

    Pass the party's own `id`: election recording, ballot casting and recovery
    action responses all compare the target resource's party reference to
    `X-User-ID`.
    """
    return build_user_headers(prp_id, "PRPRepresentative")


def make_contractor_headers(contract_id: str) -> dict:
    """Headers for the contractor of one contract.

    Pass the remediation contract's own `id`: scheduling a field-work window
    compares the contract in the path to `X-User-ID`.
    """
    return build_user_headers(contract_id, "Contractor")


def make_headers(user_id: str, role: str) -> dict:
    """An arbitrary identifier/role pair, used by the authentication probes."""
    return build_user_headers(user_id, role)
