"""Pre-built role headers for every role in PRD §2.1.

Per PRD §2.1:
- ``Streamer`` is the only ``entity_backed`` role: ``X-User-ID`` is the id of the
  acting Streamer entity, and ownership checks compare it to the resource's
  ``streamer_id``. Therefore tests that mutate streamer-owned resources MUST use
  ``make_streamer_headers(streamer_id)`` with the actual entity id.
- The other three roles (``OperationsReviewer``, ``ComplianceReviewer``,
  ``PlatformAdmin``) are ``opaque`` — ``X-User-ID`` is never compared to any
  entity id — so a stable shared constant is canonical.
"""

from prd_bench_local_runner.testing import build_user_headers


# ---------------------------------------------------------------------------
# Shared user IDs (deterministic so logs are readable)
# ---------------------------------------------------------------------------

# Opaque operator IDs — never compared against entity ids
OPS_REVIEWER_ID = "a0000000-0000-0000-0000-00000000ff01"
COMPLIANCE_REVIEWER_ID = "a0000000-0000-0000-0000-00000000ff02"
PLATFORM_ADMIN_ID = "a0000000-0000-0000-0000-00000000ff03"

# Secondary opaque ids for tests that need two distinct operators
OPS_REVIEWER_2_ID = "a0000000-0000-0000-0000-00000000ff11"
COMPLIANCE_REVIEWER_2_ID = "a0000000-0000-0000-0000-00000000ff12"

# Fallback Streamer id — used ONLY for negative tests where ownership is
# *not* the rule under test (e.g. ERR_NOT_FOUND on a non-existent application).
# Any test exercising ownership-gated behavior MUST mint headers from the
# real Streamer entity via ``make_streamer_headers(streamer.id)``.
PLACEHOLDER_STREAMER_ID = "f0000000-0000-0000-0000-0000000000ff"


# ---------------------------------------------------------------------------
# Shared header constants (opaque roles)
# ---------------------------------------------------------------------------

OPS_HEADERS = build_user_headers(OPS_REVIEWER_ID, "OperationsReviewer")
COMPLIANCE_HEADERS = build_user_headers(COMPLIANCE_REVIEWER_ID, "ComplianceReviewer")
ADMIN_HEADERS = build_user_headers(PLATFORM_ADMIN_ID, "PlatformAdmin")

OPS_HEADERS_2 = build_user_headers(OPS_REVIEWER_2_ID, "OperationsReviewer")
COMPLIANCE_HEADERS_2 = build_user_headers(COMPLIANCE_REVIEWER_2_ID, "ComplianceReviewer")

# For tests that just need *some* Streamer headers (e.g., 404 on a missing path),
# this points at a Streamer id that does not match any real entity, so any test
# that *requires* ownership for success MUST NOT use it.
PLACEHOLDER_STREAMER_HEADERS = build_user_headers(PLACEHOLDER_STREAMER_ID, "Streamer")


TEST_USERS = {
    "ops_headers": OPS_HEADERS,
    "compliance_headers": COMPLIANCE_HEADERS,
    "admin_headers": ADMIN_HEADERS,
    "ops_headers_2": OPS_HEADERS_2,
    "compliance_headers_2": COMPLIANCE_HEADERS_2,
    "placeholder_streamer_headers": PLACEHOLDER_STREAMER_HEADERS,
}


# ---------------------------------------------------------------------------
# Per-instance builder for the entity-backed Streamer role
# ---------------------------------------------------------------------------


def make_streamer_headers(streamer_id: str) -> dict:
    """Mint Streamer headers whose ``X-User-ID`` equals an actual Streamer.id.

    Required for any ownership-gated call (submit, withdraw, start-live,
    end-live, cancel, product association, appeal). Passing the wrong id here
    is precisely what would yield ``ERR_FORBIDDEN`` per PRD §2.1.
    """
    return build_user_headers(streamer_id, "Streamer")
