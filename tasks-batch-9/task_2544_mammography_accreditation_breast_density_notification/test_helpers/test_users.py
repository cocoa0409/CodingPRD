"""Auth headers for the seven roles.

Three of the seven roles are entity-backed: an `InterpretingPhysician`, a
`Technologist` and a `MedicalPhysicist` are identified by the `id` of a
`Personnel` row, and the service reads that identity out of `X-User-ID` (for
example "its `physicist_id` is taken from the caller's `X-User-ID`, never from
the body").  Any call that attributes a write to a person, or that is gated on
ownership, MUST therefore be made with a header built from the real personnel
id — use ``make_physician_headers`` / ``make_technologist_headers`` /
``make_physicist_headers``.

The four remaining roles are opaque: nothing in the service resolves an
`AccreditationCoordinator`, an `AccreditationBodyReviewer`, an `FdaInspector` or
a `QualityAssuranceOfficer` to a stored row, so a fixed id is sufficient.
"""

from prd_bench_local_runner.testing import build_user_headers

from .constants import (
    ROLE_BODY_REVIEWER,
    ROLE_COORDINATOR,
    ROLE_FDA_INSPECTOR,
    ROLE_INTERPRETING_PHYSICIAN,
    ROLE_MEDICAL_PHYSICIST,
    ROLE_QA_OFFICER,
    ROLE_TECHNOLOGIST,
)

# Fixed ids for the four opaque roles.
COORDINATOR_ID = "coord-1"
BODY_REVIEWER_ID = "reviewer-1"
FDA_INSPECTOR_ID = "inspector-1"
QA_OFFICER_ID = "qa-1"


def make_physician_headers(personnel_id: str) -> dict:
    """Headers for an `InterpretingPhysician` acting as a specific personnel row."""
    return build_user_headers(personnel_id, ROLE_INTERPRETING_PHYSICIAN)


def make_technologist_headers(personnel_id: str) -> dict:
    """Headers for a `Technologist` acting as a specific personnel row."""
    return build_user_headers(personnel_id, ROLE_TECHNOLOGIST)


def make_physicist_headers(personnel_id: str) -> dict:
    """Headers for a `MedicalPhysicist` acting as a specific personnel row."""
    return build_user_headers(personnel_id, ROLE_MEDICAL_PHYSICIST)


def make_coordinator_headers(user_id: str = COORDINATOR_ID) -> dict:
    return build_user_headers(user_id, ROLE_COORDINATOR)


def make_reviewer_headers(user_id: str = BODY_REVIEWER_ID) -> dict:
    return build_user_headers(user_id, ROLE_BODY_REVIEWER)


def make_inspector_headers(user_id: str = FDA_INSPECTOR_ID) -> dict:
    return build_user_headers(user_id, ROLE_FDA_INSPECTOR)


def make_qa_headers(user_id: str = QA_OFFICER_ID) -> dict:
    return build_user_headers(user_id, ROLE_QA_OFFICER)


TEST_USERS = {
    "coordinator_headers": build_user_headers(COORDINATOR_ID, ROLE_COORDINATOR),
    "reviewer_headers": build_user_headers(BODY_REVIEWER_ID, ROLE_BODY_REVIEWER),
    "inspector_headers": build_user_headers(FDA_INSPECTOR_ID, ROLE_FDA_INSPECTOR),
    "qa_headers": build_user_headers(QA_OFFICER_ID, ROLE_QA_OFFICER),
    # The three entity-backed entries below carry placeholder ids and are ONLY
    # safe on the read-only endpoints open to "All seven roles".  Never use them
    # for an attributed write.
    "physician_headers_readonly": build_user_headers(
        "physician-readonly", ROLE_INTERPRETING_PHYSICIAN
    ),
    "technologist_headers_readonly": build_user_headers(
        "technologist-readonly", ROLE_TECHNOLOGIST
    ),
    "physicist_headers_readonly": build_user_headers(
        "physicist-readonly", ROLE_MEDICAL_PHYSICIST
    ),
}

# An unknown role value, used to prove that authentication is rejected before
# any business rule runs.
UNKNOWN_ROLE_HEADERS = build_user_headers("someone-1", "Radiologist")

# No headers at all.
NO_HEADERS: dict = {}
