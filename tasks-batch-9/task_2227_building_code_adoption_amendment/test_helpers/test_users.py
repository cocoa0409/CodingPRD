"""Pre-built role headers for every role in the PRD (§2.1).

Three roles are entity-backed: `CommitteeMember` and `CouncilChair` carry the
`id` of a `CommitteeMember` row in `X-User-ID`, and `JurisdictionOfficial`
carries the `id` of a `Jurisdiction`. Calls made in those roles MUST be built
with the per-instance builders below, passing the real entity id, because
ownership and eligibility checks compare `X-User-ID` against a live row.

The opaque roles (`CouncilAdmin`, `TechnicalStaff`, `Petitioner`) carry operator
identifiers that the server records for accountability but never resolves, so
distinct constants are provided for the segregation-of-duties pairs of §2.9.
"""
from prd_bench_local_runner.testing import build_user_headers

# ---------------------------------------------------------------------------
# Opaque operator identifiers (PRD §2.1: never compared to any entity's id)
# ---------------------------------------------------------------------------
ADMIN_OPS_ID = "admin-ops-1"
ADMIN_REVIEWER_ID = "admin-reviewer-1"
ADMIN_SECOND_REVIEWER_ID = "admin-reviewer-2"
ADMIN_RULE_DRAFTER_ID = "admin-rule-1"
ADMIN_FILER_ID = "admin-filer-1"
ADMIN_PUBLISHER_ID = "admin-publisher-1"
ADMIN_EFFECTIVE_ID = "admin-effective-1"
ADMIN_LOCAL_REVIEWER_ID = "admin-local-1"
ADMIN_OPINION_PUBLISHER_ID = "admin-opinion-1"

STAFF_INTAKE_ID = "staff-intake-1"
STAFF_ANALYST_ID = "staff-analyst-1"
STAFF_SECOND_ANALYST_ID = "staff-analyst-2"
STAFF_DRAFTER_ID = "staff-drafter-1"
STAFF_SECOND_DRAFTER_ID = "staff-drafter-2"

PETITIONER_ONE_ID = "petitioner-1"
PETITIONER_TWO_ID = "petitioner-2"
PETITIONER_THREE_ID = "petitioner-3"
PETITIONER_FOUR_ID = "petitioner-4"
PETITIONER_NINE_ID = "petitioner-9"

# An identifier of the right shape that resolves to no live row, for the one
# rung of the ladder that reports an unresolvable entity-backed identity.
UNKNOWN_IDENTITY_ID = "00000000-0000-0000-0000-0000000000aa"


# ---------------------------------------------------------------------------
# Shared constants — safe for the opaque roles, and for tests that exercise no
# ownership check (bad payloads, unknown identifiers, pagination shape).
# ---------------------------------------------------------------------------
TEST_USERS = {
    "council_admin_headers": build_user_headers(ADMIN_OPS_ID, "CouncilAdmin"),
    "technical_staff_headers": build_user_headers(STAFF_INTAKE_ID, "TechnicalStaff"),
    "petitioner_headers": build_user_headers(PETITIONER_ONE_ID, "Petitioner"),
    # The three entity-backed roles: these placeholders resolve to no live row,
    # so they are only appropriate where the PRD expects that very failure.
    "committee_member_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000aa", "CommitteeMember"
    ),
    "council_chair_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000aa", "CouncilChair"
    ),
    "jurisdiction_official_headers": build_user_headers(
        "00000000-0000-0000-0000-0000000000aa", "JurisdictionOfficial"
    ),
}


# ---------------------------------------------------------------------------
# Per-instance builders
# ---------------------------------------------------------------------------
def make_anonymous_headers() -> dict:
    """Headers carrying no `X-User-ID` at all, for the one rung of the ladder
    that runs before any role is known."""
    return {"Content-Type": "application/json"}


def make_headers_without_identity(role: str = "CouncilAdmin") -> dict:
    """Headers naming a role but carrying an empty `X-User-ID`, for the rung that
    requires both header values to be present and non-empty."""
    return build_user_headers("", role)


def make_council_admin_headers(user_id: str = ADMIN_OPS_ID) -> dict:
    """CouncilAdmin headers. The identifier is opaque but is recorded on the
    record it touches, so pass a distinct one on each side of a
    segregation-of-duties pair."""
    return build_user_headers(user_id, "CouncilAdmin")


def make_technical_staff_headers(user_id: str = STAFF_INTAKE_ID) -> dict:
    """TechnicalStaff headers; the identifier lands in `prepared_by_user_id`
    and `drafted_by_user_id`."""
    return build_user_headers(user_id, "TechnicalStaff")


def make_petitioner_headers(user_id: str = PETITIONER_ONE_ID) -> dict:
    """Petitioner headers; the identifier lands in `submitted_by_user_id` and
    `requested_by_user_id`."""
    return build_user_headers(user_id, "Petitioner")


def make_committee_member_headers(member_id: str) -> dict:
    """CommitteeMember headers. `X-User-ID` must be the `id` of a live
    `CommitteeMember` row, or the request fails with ERR_IDENTITY_NOT_FOUND."""
    return build_user_headers(member_id, "CommitteeMember")


def make_council_chair_headers(member_id: str) -> dict:
    """CouncilChair headers. `X-User-ID` must be the `id` of the presiding
    `CommitteeMember` row of the hearing's committee."""
    return build_user_headers(member_id, "CouncilChair")


def make_jurisdiction_official_headers(jurisdiction_id: str) -> dict:
    """JurisdictionOfficial headers. `X-User-ID` must be the `id` of the acting
    `Jurisdiction`; ownership checks compare resource foreign keys to it."""
    return build_user_headers(jurisdiction_id, "JurisdictionOfficial")
