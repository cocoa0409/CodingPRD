"""Non-linear (cyclic) state-machine tests (Difficulty queue:
non_linear_state_machine)."""
import pytest

from test_helpers import (
    validate_success,
    OWNER, CONTRACTOR, ARCHITECT,
    create_project,
)
from test_helpers import api_client


# ===========================================================================
# Rule: non_linear_state_machine
# ===========================================================================
class TestPunchItemCyclicVerifiedReopenedReady:
    """Design: Difficulty/non_linear_state_machine/punch_item_cyclic_verified_reopened_ready"""

    def _verified_punch_item(self, api, project_id):
        pi = validate_success(
            api.create_punch_item(
                {"project_id": project_id, "location": "Lobby",
                 "description": "Paint chip", "severity": "MINOR"},
                ARCHITECT,
            ),
            201,
        )
        validate_success(api.ready_punch_item(pi["id"], CONTRACTOR), 200)
        validate_success(api.verify_punch_item(pi["id"], ARCHITECT), 200)
        return pi

    def test_reopen_from_verified_lands_in_reopened(self, api):
        """PRD §3.7: "A reopen is legal from either READY_FOR_REVIEW or VERIFIED and lands
        the item in REOPENED, forming the cyclic loop READY_FOR_REVIEW → REOPENED →
        READY_FOR_REVIEW."

        Design: Difficulty/non_linear_state_machine/punch_item_cyclic_verified_reopened_ready
        """
        project = create_project(500_000, name="PunchProj")
        pi = self._verified_punch_item(api, project["id"])
        data = validate_success(api.reopen_punch_item(pi["id"], ARCHITECT), 200)
        assert data["status"] == "REOPENED"

    def test_full_cycle_returns_to_verified(self, api):
        """PRD §3.7: "The Contractor marks an item ready for review — legal from either OPEN
        or REOPENED, advancing the item to READY_FOR_REVIEW. The Architect then either
        verifies it, moving READY_FOR_REVIEW → VERIFIED".

        Design: Difficulty/non_linear_state_machine/punch_item_cyclic_verified_reopened_ready
        """
        project = create_project(500_000, name="PunchProj2")
        pi = self._verified_punch_item(api, project["id"])
        validate_success(api.reopen_punch_item(pi["id"], ARCHITECT), 200)
        ready = validate_success(api.ready_punch_item(pi["id"], CONTRACTOR), 200)
        assert ready["status"] == "READY_FOR_REVIEW"  # re-entered the same state.
        verified = validate_success(api.verify_punch_item(pi["id"], ARCHITECT), 200)
        assert verified["status"] == "VERIFIED"  # loop closed.


class TestSubmittalCyclicReviseResubmitRevisionBump:
    """Design: Difficulty/non_linear_state_machine/submittal_cyclic_revise_resubmit_revision_bump"""

    def _submittal_in_revise(self, api, project_id):
        sub = validate_success(
            api.create_submittal(
                {"project_id": project_id, "spec_section": "03 30 00",
                 "title": "Concrete mix"},
                CONTRACTOR,
            ),
            201,
        )
        validate_success(
            api.review_submittal(sub["id"], {"decision": "REVISE_AND_RESUBMIT"}, ARCHITECT),
            200,
        )
        return sub

    def test_review_revise_sets_revise_and_resubmit(self, api):
        """PRD §3.5: "a decision of REVISE_AND_RESUBMIT moves it PENDING → REVISE_AND_RESUBMIT."

        Design: Difficulty/non_linear_state_machine/submittal_cyclic_revise_resubmit_revision_bump
        """
        project = create_project(500_000, name="SubProj")
        sub = self._submittal_in_revise(api, project["id"])
        data = validate_success(api.get_submittal(sub["id"], OWNER), 200)
        assert data["status"] == "REVISE_AND_RESUBMIT"
        assert data["revision"] == 0

    def test_resubmit_returns_to_pending_and_bumps_revision(self, api):
        """PRD §3.5: "this advances REVISE_AND_RESUBMIT → PENDING and increments revision by
        one, the cyclic revision loop that lets a submittal cycle through review as many
        times as the design requires."

        Design: Difficulty/non_linear_state_machine/submittal_cyclic_revise_resubmit_revision_bump
        """
        project = create_project(500_000, name="SubProj2")
        sub = self._submittal_in_revise(api, project["id"])
        data = validate_success(api.resubmit_submittal(sub["id"], CONTRACTOR), 200)
        assert data["status"] == "PENDING"  # returned to PENDING — cyclic.
        assert data["revision"] == 1  # incremented from 0.
