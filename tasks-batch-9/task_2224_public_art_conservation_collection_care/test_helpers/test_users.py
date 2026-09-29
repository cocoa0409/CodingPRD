"""Pre-built role headers for every role in the PRD (§2.1).

Seven roles carry an opaque operator identifier in `X-User-ID`.  Two roles are
backed by a persisted entity: `ArtistRepresentative` carries the acting
`Artist.id` and `ConservatorVendor` carries the acting `Conservator.id`, so for
those two the shared constants below are useful only where the call is not
ownership-gated — every ownership-gated call must build headers from the real
entity id with the matching `make_*_headers()` builder.
"""

from prd_bench_local_runner.testing import build_user_headers

# Opaque operator identifiers used consistently across the suite.
REGISTRAR_USER_ID = "reg-1"
SURVEYOR_USER_ID = "surv-1"
SECOND_SURVEYOR_USER_ID = "surv-2"
CHIEF_CONSERVATOR_USER_ID = "chief-1"
CREW_USER_ID = "crew-1"
MANAGER_USER_ID = "mgr-1"
FINANCE_USER_ID = "fin-1"
COMMISSION_MEMBER_USER_IDS = ["acm-1", "acm-2", "acm-3", "acm-4", "acm-5"]

TEST_USERS = {
    "registrar_headers": build_user_headers(REGISTRAR_USER_ID, "CollectionsRegistrar"),
    "surveyor_headers": build_user_headers(SURVEYOR_USER_ID, "ConditionSurveyor"),
    "second_surveyor_headers": build_user_headers(
        SECOND_SURVEYOR_USER_ID, "ConditionSurveyor"
    ),
    "chief_conservator_headers": build_user_headers(
        CHIEF_CONSERVATOR_USER_ID, "ChiefConservator"
    ),
    "crew_headers": build_user_headers(CREW_USER_ID, "MaintenanceCrew"),
    "manager_headers": build_user_headers(MANAGER_USER_ID, "PublicArtManager"),
    "finance_headers": build_user_headers(FINANCE_USER_ID, "FinanceOfficer"),
    "commission_member_headers": build_user_headers("acm-1", "ArtCommissionMember"),
    # Entity-backed roles: these shared constants are a fallback for tests that
    # do not exercise ownership (for example a 404 on a missing resource).
    "artist_representative_headers": build_user_headers(
        "unowned-artist-id", "ArtistRepresentative"
    ),
    "conservator_vendor_headers": build_user_headers(
        "unowned-conservator-id", "ConservatorVendor"
    ),
}


# --- Per-instance builders for the two entity-backed roles -----------------
def make_artist_representative_headers(artist_id: str) -> dict:
    """For ArtistRepresentative: `X-User-ID` is the acting `Artist.id`."""
    return build_user_headers(artist_id, "ArtistRepresentative")


def make_conservator_vendor_headers(conservator_id: str) -> dict:
    """For ConservatorVendor: `X-User-ID` is the acting `Conservator.id`."""
    return build_user_headers(conservator_id, "ConservatorVendor")


# --- Per-instance builders for the opaque roles ----------------------------
def make_registrar_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "CollectionsRegistrar")


def make_surveyor_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ConditionSurveyor")


def make_chief_conservator_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ChiefConservator")


def make_crew_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "MaintenanceCrew")


def make_manager_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "PublicArtManager")


def make_finance_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "FinanceOfficer")


def make_commission_member_headers(user_id: str) -> dict:
    return build_user_headers(user_id, "ArtCommissionMember")


def make_headers(user_id: str, role: str) -> dict:
    """Free-form builder for role-authorization sweeps."""
    return build_user_headers(user_id, role)
