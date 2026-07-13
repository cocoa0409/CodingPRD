"""The tribute-video cyclic review loop.

Queue-A non-linear-state-machine instance for the revision back-edge, plus the
queue-B invalid-transition corner.
"""
from test_helpers import (
    TEST_USERS,
    validate_error, ApiErrorId,
    setup_draft_order, create_tribute, transition_tribute,
)

ADMIN = TEST_USERS["admin_headers"]


def _resubmitted_tribute():
    """DRAFT tribute driven SUBMIT -> REQUEST_CHANGES -> SUBMIT (one revision loop)."""
    base = setup_draft_order(
        scheduled_start="2026-06-05T10:00:00Z", scheduled_end="2026-06-05T11:00:00Z",
    )
    tv = create_tribute(base["order"]["id"], title="In Memory", photo_count=20)
    transition_tribute(tv["id"], "SUBMIT")
    transition_tribute(tv["id"], "REQUEST_CHANGES")
    return transition_tribute(tv["id"], "SUBMIT")


def test_resubmit_returns_status_to_submitted(api):
    """PRD §3.10: "When changes were requested, the home resubmits, moving
    `status` from `CHANGES_REQUESTED` back to `SUBMITTED` and incrementing
    `revision_count` by one — this back-edge is the revision loop, and it is the
    only transition that bumps the revision counter."

    Design: Difficulty/non_linear_state_machine/tribute_video_revision_cycle_increments_revision_count
    """
    tv = _resubmitted_tribute()
    assert tv["status"] == "SUBMITTED"


def test_resubmit_increments_revision_count(api):
    """PRD §3.10: "When changes were requested, the home resubmits, moving
    `status` from `CHANGES_REQUESTED` back to `SUBMITTED` and incrementing
    `revision_count` by one — this back-edge is the revision loop, and it is the
    only transition that bumps the revision counter."

    Design: Difficulty/non_linear_state_machine/tribute_video_revision_cycle_increments_revision_count
    """
    tv = _resubmitted_tribute()
    assert tv["revision_count"] == 1


def test_publish_draft_tribute_rejected(api):
    """PRD §3.10: "Finally the home publishes an approved tribute, advancing
    `status` from `APPROVED` to `PUBLISHED`. Any tribute action attempted from a
    state that does not permit it is rejected with `ERR_TRIBUTE_INVALID_TRANSITION`."

    Design: Corner/state_machines/tribute_publish_from_draft_returns_invalid_transition
    """
    base = setup_draft_order(
        scheduled_start="2026-06-21T10:00:00Z", scheduled_end="2026-06-21T11:00:00Z",
    )
    tv = create_tribute(base["order"]["id"], title="Draft Reel", photo_count=5)
    resp = api.transition_tribute_video(tv["id"], {"action": "PUBLISH"}, ADMIN)
    validate_error(resp, ApiErrorId.ERR_TRIBUTE_INVALID_TRANSITION)
