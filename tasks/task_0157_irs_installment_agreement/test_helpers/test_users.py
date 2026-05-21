"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

    "When X-User-Role is Taxpayer, X-User-ID is the id of the acting
    Taxpayer entity; ownership checks on any resource that references a
    Taxpayer (a TaxLiability, InstallmentAgreement, OfferInCompromise,
    FederalTaxLien, CNCStatus, ReconsiderationRequest, or Payment)
    compare the resource's taxpayer_id to X-User-ID, and a mismatch is
    rejected with ERR_FORBIDDEN. When X-User-Role is IRSOfficer or
    OICOfficer, X-User-ID is an opaque operator identifier not tied to
    any persisted entity."

Only Taxpayer is entity_backed (entity_backed:Taxpayer). The two
officer roles are opaque — a shared deterministic id is the canonical
form for them.

Per PRD §2.8, OICOfficer and IRSOfficer also enforce segregation of
duties:

    "Within the Offer in Compromise pipeline, the OICOfficer who takes
    up a submitted offer cannot be the same operator who later issues
    the accept or reject decision; a mismatched decision attempt is
    rejected with ERR_SEGREGATION_OF_DUTIES."

    "Within the reconsideration pipeline, the IRSOfficer who originally
    activated an installment agreement cannot be the same operator who
    later decides a reconsideration on that agreement; a mismatched
    decision attempt is rejected with the same ERR_SEGREGATION_OF_DUTIES
    code."

Tests of the SoD rule must use DIFFERENT opaque operator ids. The
per-operator builders make_irs_officer_headers(operator_id) and
make_oic_officer_headers(operator_id) mint unique identities when SoD
is load-bearing.

The shared *_headers constants are appropriate for tests that don't
exercise ownership or SoD identity — auth probes, role-forbidden probes,
404 probes — and for IRSOfficer / OICOfficer calls outside the SoD
pipelines.

The mandatory builder is make_taxpayer_headers(taxpayer_id). Fixtures
that create a Taxpayer and then act as that Taxpayer (e.g., draft +
submit an OIC, file a payment, open a reconsideration request) MUST
mint headers with that Taxpayer.id rather than reusing the shared
constant — otherwise the server's ownership check
(resource.taxpayer_id == X-User-ID) would reject the call.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Bootstrap / shared operator ids for the two opaque officer roles.
# ---------------------------------------------------------------------------
IRS_OFFICER_SHARED_ID: str = "irs-officer-op-0001"
IRS_OFFICER_SECONDARY_ID: str = "irs-officer-op-0002"
OIC_OFFICER_SHARED_ID: str = "oic-officer-op-0001"
OIC_OFFICER_SECONDARY_ID: str = "oic-officer-op-0002"

# Taxpayer is entity_backed — this shared id is a placeholder that
# resolves to no real Taxpayer. It is appropriate for auth /
# role-forbidden / 404 probes only; any test whose success depends on
# the taxpayer owning the resource MUST use
# make_taxpayer_headers(taxpayer_id) with a real Taxpayer.id.
TAXPAYER_SHARED_ID: str = "taxpayer-placeholder-0001"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # entity_backed:Taxpayer — shared constant for non-ownership tests only.
    "taxpayer_headers": build_user_headers(TAXPAYER_SHARED_ID, "Taxpayer"),
    # opaque operator roles — shared constants are canonical.
    "irs_officer_headers": build_user_headers(
        IRS_OFFICER_SHARED_ID, "IRSOfficer",
    ),
    "irs_officer_secondary_headers": build_user_headers(
        IRS_OFFICER_SECONDARY_ID, "IRSOfficer",
    ),
    "oic_officer_headers": build_user_headers(
        OIC_OFFICER_SHARED_ID, "OICOfficer",
    ),
    "oic_officer_secondary_headers": build_user_headers(
        OIC_OFFICER_SECONDARY_ID, "OICOfficer",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builder — MANDATORY for entity_backed:Taxpayer role.
#
# PRD §2.1: "ownership checks on any resource that references a Taxpayer
# ... compare the resource's taxpayer_id to X-User-ID."
# ---------------------------------------------------------------------------
def make_taxpayer_headers(taxpayer_id: str) -> Dict[str, str]:
    """Headers for a specific Taxpayer acting as caller. Use this
    whenever the call is gated on resource.taxpayer_id == X-User-ID
    (e.g., OIC submit/withdraw, payment recording, reconsideration
    request, GET of own resources).
    """
    return build_user_headers(taxpayer_id, "Taxpayer")


# ---------------------------------------------------------------------------
# Per-operator builders for opaque officer roles. Use these when a test
# needs two distinct operators of the same role for SoD checks.
# ---------------------------------------------------------------------------
def make_irs_officer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "IRSOfficer")


def make_oic_officer_headers(operator_id: str) -> Dict[str, str]:
    return build_user_headers(operator_id, "OICOfficer")


__all__ = [
    "IRS_OFFICER_SHARED_ID",
    "IRS_OFFICER_SECONDARY_ID",
    "OIC_OFFICER_SHARED_ID",
    "OIC_OFFICER_SECONDARY_ID",
    "TAXPAYER_SHARED_ID",
    "TEST_USERS",
    "make_taxpayer_headers",
    "make_irs_officer_headers",
    "make_oic_officer_headers",
]
