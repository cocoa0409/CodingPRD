"""Acting-operator headers for each of the seven studio roles.

PRD §2.1 splits identity in two. Five roles carry **opaque** identity: their
`X-User-ID` "is an opaque operator identifier that is not tied to any persisted
entity", so a single shared constant per role is correct and stable.

`Photographer` and `Retoucher` are **entity-backed**: "X-User-ID is not a
free-form operator string but a primary key" — the `id` of the acting
`TalentProfile`. Those two roles therefore have no shared constant at all;
callers must build headers per talent row with `make_photographer_headers()`
and `make_retoucher_headers()`.

`QCReviewer` is opaque but its identifier is not inert — it "is compared, as a
plain string, against the assigned_retoucher_id of the task under review", so
`make_qc_reviewer_headers()` exists to let a test act as a reviewer whose id
deliberately equals some retoucher's id.
"""

from typing import Dict

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_CONTENT_OPS,
    ROLE_PHOTOGRAPHER,
    ROLE_PRODUCER,
    ROLE_QC_REVIEWER,
    ROLE_RETOUCHER,
    ROLE_SAMPLE_COORDINATOR,
    ROLE_STUDIO_ADMIN,
)

# ─── Opaque operator identifiers ───────────────────────────────────────────
STUDIO_ADMIN_ID = "studio-admin-01"
SAMPLE_COORDINATOR_ID = "sample-coordinator-01"
PRODUCER_ID = "producer-01"
QC_REVIEWER_ID = "qc-reviewer-01"
CONTENT_OPS_ID = "content-ops-01"

TEST_USERS: Dict[str, Dict[str, str]] = {
    ROLE_STUDIO_ADMIN: build_user_headers(STUDIO_ADMIN_ID, ROLE_STUDIO_ADMIN),
    ROLE_SAMPLE_COORDINATOR: build_user_headers(
        SAMPLE_COORDINATOR_ID, ROLE_SAMPLE_COORDINATOR
    ),
    ROLE_PRODUCER: build_user_headers(PRODUCER_ID, ROLE_PRODUCER),
    ROLE_QC_REVIEWER: build_user_headers(QC_REVIEWER_ID, ROLE_QC_REVIEWER),
    ROLE_CONTENT_OPS: build_user_headers(CONTENT_OPS_ID, ROLE_CONTENT_OPS),
}

# Convenience aliases for the five opaque roles.
ADMIN = TEST_USERS[ROLE_STUDIO_ADMIN]
COORDINATOR = TEST_USERS[ROLE_SAMPLE_COORDINATOR]
PRODUCER = TEST_USERS[ROLE_PRODUCER]
QC_REVIEWER = TEST_USERS[ROLE_QC_REVIEWER]
CONTENT_OPS = TEST_USERS[ROLE_CONTENT_OPS]


# ─── Entity-backed roles ───────────────────────────────────────────────────

def make_photographer_headers(talent_id: str) -> Dict[str, str]:
    """Headers for a Photographer acting as the TalentProfile whose id is given."""
    return build_user_headers(talent_id, ROLE_PHOTOGRAPHER)


def make_retoucher_headers(talent_id: str) -> Dict[str, str]:
    """Headers for a Retoucher acting as the TalentProfile whose id is given."""
    return build_user_headers(talent_id, ROLE_RETOUCHER)


def make_qc_reviewer_headers(user_id: str) -> Dict[str, str]:
    """Headers for a QCReviewer acting under an arbitrary opaque identifier."""
    return build_user_headers(user_id, ROLE_QC_REVIEWER)


def make_headers(user_id: str, role: str) -> Dict[str, str]:
    """Headers for an arbitrary user id / role string pair."""
    return build_user_headers(user_id, role)
