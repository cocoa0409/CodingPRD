"""Pre-built role headers for every role the PRD recognises (PRD §2.1).

PRD §2.1: all five roles — `Sponsor`, `IRBReviewer`, `CoordinatorStaff`,
`Investigator`, and `SafetyOfficer` — are **opaque operator identities**.
`X-User-ID` is an operator identifier that the server never compares to any
entity's `id`. It IS, however, recorded as an audit anchor where the workflow
demands it (a trial's `sponsor_user_id`, an adverse event's `reporter_user_id`)
and those recorded identifiers drive the segregation-of-duties checks.

Because the identifiers matter for segregation of duties (an IRBReviewer's
`X-User-ID` must differ from the trial's `sponsor_user_id`; a SafetyOfficer's
`X-User-ID` must differ from the adverse event's `reporter_user_id`), this file
emits BOTH shared constants (for tests that do not exercise an identity check)
and per-role builders so a test can pin a specific operator id.

There are no `entity_backed` roles in this PRD, so no builder threads an
entity's `id` as `X-User-ID`.
"""
from prd_bench_local_runner.testing import build_user_headers


# Stable operator ids reused by the composite fixtures.
SPONSOR_USER_ID = "sponsor-1"
IRB_REVIEWER_USER_ID = "irb-1"
COORDINATOR_USER_ID = "coord-1"
INVESTIGATOR_USER_ID = "inv-1"
SAFETY_OFFICER_USER_ID = "so-1"


TEST_USERS = {
    "sponsor_headers": build_user_headers(SPONSOR_USER_ID, "Sponsor"),
    "irb_reviewer_headers": build_user_headers(IRB_REVIEWER_USER_ID, "IRBReviewer"),
    "coordinator_headers": build_user_headers(COORDINATOR_USER_ID, "CoordinatorStaff"),
    "investigator_headers": build_user_headers(INVESTIGATOR_USER_ID, "Investigator"),
    "safety_officer_headers": build_user_headers(SAFETY_OFFICER_USER_ID, "SafetyOfficer"),
}


# ─── Per-role builders (pin a specific operator X-User-ID) ──


def make_sponsor_headers(user_id: str = SPONSOR_USER_ID) -> dict:
    """Sponsor headers. Pass a specific operator id when its value matters as
    a segregation-of-duties anchor (the trial's recorded `sponsor_user_id`)."""
    return build_user_headers(user_id, "Sponsor")


def make_irb_reviewer_headers(user_id: str = IRB_REVIEWER_USER_ID) -> dict:
    """IRBReviewer headers. Pin a specific operator id to exercise the
    sponsor-vs-reviewer segregation-of-duties check (PRD §3.2)."""
    return build_user_headers(user_id, "IRBReviewer")


def make_coordinator_headers(user_id: str = COORDINATOR_USER_ID) -> dict:
    return build_user_headers(user_id, "CoordinatorStaff")


def make_investigator_headers(user_id: str = INVESTIGATOR_USER_ID) -> dict:
    """Investigator headers; the operator id is recorded as the adverse
    event's `reporter_user_id` segregation anchor (PRD §2.1, §3.5)."""
    return build_user_headers(user_id, "Investigator")


def make_safety_officer_headers(user_id: str = SAFETY_OFFICER_USER_ID) -> dict:
    """SafetyOfficer headers. Pin a specific operator id to exercise the
    reporter-vs-reviewer segregation-of-duties check (PRD §3.5)."""
    return build_user_headers(user_id, "SafetyOfficer")
