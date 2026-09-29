"""Auth headers for each of the six roles.

Three roles are backed by a persisted row, so their ``X-User-ID`` must be the
identifier of a real entity created earlier in the same scenario: a
``SchoolCertifyingOfficial`` and a ``SupervisorySCO`` carry the ``id`` of the
acting certifying official, and a ``Student`` carries the ``id`` of the acting
veteran student. Those three therefore have per-instance builders rather than
module-level constants — a shared placeholder identifier would fail the
registration, activity and level gates, or the student scope check.

The other three roles present an opaque operator identifier that the server
never resolves against any row, so a fixed constant is correct for them.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BURSAR_OFFICER,
    ROLE_SCHOOL_CERTIFYING_OFFICIAL,
    ROLE_STATE_APPROVING_AGENT,
    ROLE_STUDENT,
    ROLE_SUPERVISORY_SCO,
    ROLE_VA_PROCESSING_OFFICE,
)
from .types import Headers

# ─── Opaque operator identities ───────────────────────────────────────
BURSAR_OPERATOR_ID = "bursar-operator-01"
SAA_OPERATOR_ID = "saa-reviewer-01"
VA_OPERATOR_ID = "va-processing-01"

BURSAR_HEADERS: Headers = build_user_headers(BURSAR_OPERATOR_ID, ROLE_BURSAR_OFFICER)
SAA_HEADERS: Headers = build_user_headers(SAA_OPERATOR_ID, ROLE_STATE_APPROVING_AGENT)
VA_HEADERS: Headers = build_user_headers(VA_OPERATOR_ID, ROLE_VA_PROCESSING_OFFICE)


# ─── Entity-backed identities ─────────────────────────────────────────
def make_sco_headers(official_id: str) -> Headers:
    """Headers for a front-line certifying official acting as themselves."""
    return build_user_headers(official_id, ROLE_SCHOOL_CERTIFYING_OFFICIAL)


def make_supervisory_sco_headers(official_id: str) -> Headers:
    """Headers for a supervisory certifying official acting as themselves."""
    return build_user_headers(official_id, ROLE_SUPERVISORY_SCO)


def make_student_headers(student_id: str) -> Headers:
    """Headers for a veteran student acting on their own record."""
    return build_user_headers(student_id, ROLE_STUDENT)


def make_headers(user_id: str, role: str) -> Headers:
    """Headers for an arbitrary identifier and role pairing."""
    return build_user_headers(user_id, role)
