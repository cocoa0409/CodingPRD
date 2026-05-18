"""Pre-built role headers for every role in the PRD.

PRD §2.1 identity rules:

- Grantor is OPAQUE. PRD §2.1: "Grantor identity is opaque: there is
  no persisted Grantor entity. When X-User-Role is Grantor, X-User-ID
  is an opaque identifier not tied to any stored entity record. The
  server records this identifier on a Trust at creation time as
  grantor_user_id, and subsequent ownership checks on Trust-scoped
  grantor operations compare the supplied X-User-ID against the
  Trust's grantor_user_id."

  Although Grantor is opaque, ownership checks on Trust-scoped
  grantor operations (PATCH /trusts/{id}, POST /trusts/{id}/activate,
  POST /trusts/{id}/revoke, POST /trusts/{id}/trustees,
  POST /trusts/{id}/beneficiaries) compare X-User-ID against
  Trust.grantor_user_id. The same X-User-ID string MUST be used both
  when creating the trust and when later operating on it as Grantor;
  otherwise the ownership check rejects the request.

- Trustee is ENTITY-BACKED. PRD §2.1: "When X-User-Role is Trustee,
  X-User-ID is the user_id of an existing Trustee record under the
  trust referenced in the URL path, and that Trustee record must
  have status equal to ACTIVE. Ownership and segregation-of-duties
  checks on Distribution operations compare X-User-ID against the
  Trustee.user_id registered on the target trust."

  Every Trustee-acting call whose success depends on owning a
  Trustee record under the trust MUST mint headers via
  make_trustee_headers(trustee.user_id) — never via a shared
  constant that would fail every ownership check.

- Beneficiary is ENTITY-BACKED. PRD §2.1: "When X-User-Role is
  Beneficiary, X-User-ID is the id of an existing Beneficiary
  record. Ownership filtering on Beneficiary-scoped reads compares
  the resource's beneficiary_id (or, for the Beneficiary record
  itself, its id) to X-User-ID."

  Every Beneficiary-acting call whose success depends on owning the
  targeted Beneficiary record MUST mint headers via
  make_beneficiary_headers(beneficiary["id"]).

- TaxPreparer and Auditor are OPAQUE. PRD §2.1: "X-User-ID is an
  opaque operator identifier not tied to any persisted entity".
  Shared constants are canonical.

The shared TRUSTEE_FALLBACK / BENEFICIARY_FALLBACK constants are ONLY
safe for tests that DO NOT exercise ownership — header-missing,
role-mismatch, or 404-on-nonexistent-resource paths.
"""
from __future__ import annotations

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Canonical opaque-actor identifiers — PRD §2.1.
#
# Grantor identifiers below are CONVENIENT defaults for tests that mint
# a brand-new Trust. The same identifier MUST be threaded into both the
# create_trust call and any later ownership-gated grantor operation;
# helpers in fixtures.py do this by recording the grantor X-User-ID
# alongside the trust they return.
# ---------------------------------------------------------------------------
GRANTOR_ID: str = "grantor-user-001"
GRANTOR_ID_ALT: str = "grantor-user-002"

TAX_PREPARER_ID: str = "tax-preparer-001"
AUDITOR_ID: str = "auditor-001"

# Entity-backed fallback ids — DO NOT use for ownership-gated calls.
# Safe only for header-missing / role-mismatch / 404-on-nonexistent
# paths.
TRUSTEE_FALLBACK_ID: str = "fallback-trustee-user-1"
BENEFICIARY_FALLBACK_ID: str = "fallback-beneficiary-1"


TEST_USERS: Dict[str, Dict[str, str]] = {
    # Grantor — opaque (but PRD §2.1 requires X-User-ID == Trust.grantor_user_id
    # for ownership-gated trust operations; helpers thread this).
    "grantor_headers": build_user_headers(GRANTOR_ID, "Grantor"),
    "grantor_headers_alt": build_user_headers(GRANTOR_ID_ALT, "Grantor"),

    # TaxPreparer — opaque, shared constant canonical.
    "tax_preparer_headers": build_user_headers(
        TAX_PREPARER_ID, "TaxPreparer",
    ),

    # Auditor — opaque, shared constant canonical.
    "auditor_headers": build_user_headers(AUDITOR_ID, "Auditor"),

    # Entity-backed Trustee fallback — DO NOT use for ownership-gated
    # Trustee calls. Safe only for header-missing / role-mismatch /
    # 404-on-nonexistent paths.
    "trustee_fallback_headers": build_user_headers(
        TRUSTEE_FALLBACK_ID, "Trustee",
    ),

    # Entity-backed Beneficiary fallback — same caveat as Trustee
    # fallback.
    "beneficiary_fallback_headers": build_user_headers(
        BENEFICIARY_FALLBACK_ID, "Beneficiary",
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders — REQUIRED for entity-backed roles.
#
# Tests that hit an ownership-gated endpoint MUST mint headers via the
# matching builder, supplying the runtime id the implementation
# compares against. Falling back to the shared constants above for
# ownership-gated calls reproduces the canonical bug: the literal
# fallback string never equals any real entity's id, so every
# ownership check rejects every request.
# ---------------------------------------------------------------------------
def make_grantor_headers(grantor_user_id: str) -> Dict[str, str]:
    """For Grantor (opaque, but Trust.grantor_user_id is recorded at
    Trust creation time and compared on later grantor-scoped calls).

    PRD §2.1: "The server records this identifier on a Trust at
    creation time as grantor_user_id, and subsequent ownership checks
    on Trust-scoped grantor operations compare the supplied X-User-ID
    against the Trust's grantor_user_id."

    Tests that mint a Trust via create_trust MUST reuse the same
    X-User-ID for later activate / revoke / patch / add-trustee /
    add-beneficiary calls. fixtures.py threads this for you.
    """
    return build_user_headers(grantor_user_id, "Grantor")


def make_trustee_headers(trustee_user_id: str) -> Dict[str, str]:
    """For Trustee (entity_backed:Trustee). Pass the user_id of the
    Trustee record under the target trust.

    PRD §2.1: "When X-User-Role is Trustee, X-User-ID is the user_id
    of an existing Trustee record under the trust referenced in the
    URL path, and that Trustee record must have status equal to
    ACTIVE."

    Every Trustee-driven call whose success depends on Trustee record
    ownership (record-transaction, approve-distribution, execute,
    reject, terminate-beneficiary, terminate-trust) MUST use this
    builder. Note that ApproveDistribution further requires the
    acting trustee's X-User-ID to differ from
    Distribution.proposed_by_user_id, so tests routinely mint at
    least TWO distinct trustee user_ids per trust.
    """
    return build_user_headers(trustee_user_id, "Trustee")


def make_beneficiary_headers(beneficiary_id: str) -> Dict[str, str]:
    """For Beneficiary (entity_backed:Beneficiary). Pass the
    Beneficiary record's id.

    PRD §2.1: "When X-User-Role is Beneficiary, X-User-ID is the id
    of an existing Beneficiary record. Ownership filtering on
    Beneficiary-scoped reads compares the resource's beneficiary_id
    (or, for the Beneficiary record itself, its id) to X-User-ID."

    Every Beneficiary read whose success depends on Beneficiary
    ownership (own K-1 list, own K-1 detail, own beneficiary record,
    own distribution detail) MUST use this builder.
    """
    return build_user_headers(beneficiary_id, "Beneficiary")


def make_tax_preparer_headers(operator_id: str) -> Dict[str, str]:
    """For TaxPreparer (opaque). Any non-empty operator id works; this
    builder exists so tests that want a distinct preparer id (e.g.,
    for audit-token discrimination) can supply one.
    """
    return build_user_headers(operator_id, "TaxPreparer")


def make_auditor_headers(operator_id: str) -> Dict[str, str]:
    """For Auditor (opaque, no ownership filter — PRD §2.1: 'no
    ownership filter is applied, and the auditor sees all trusts and
    all nested resources')."""
    return build_user_headers(operator_id, "Auditor")


__all__ = [
    "GRANTOR_ID",
    "GRANTOR_ID_ALT",
    "TAX_PREPARER_ID",
    "AUDITOR_ID",
    "TRUSTEE_FALLBACK_ID",
    "BENEFICIARY_FALLBACK_ID",
    "TEST_USERS",
    "make_grantor_headers",
    "make_trustee_headers",
    "make_beneficiary_headers",
    "make_tax_preparer_headers",
    "make_auditor_headers",
]
