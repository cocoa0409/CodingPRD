"""Design licensing workflow: revision loop, invalid transitions, RBAC, OCC."""
import pytest

from test_helpers import (
    ApiErrorId,
    create_active_program,
    create_design,
    design_transition,
    submit_design,
    TEST_USERS,
    validate_error,
    validate_success,
)

DIRECTOR = TEST_USERS["director_headers"]
MANAGER = TEST_USERS["store_manager_headers"]
COORDINATOR = TEST_USERS["coordinator_headers"]
TREASURER = TEST_USERS["treasurer_headers"]


class TestDesignResubmissionCycle:
    def test_revision_count_accrues_once_per_resubmission(self, api):
        """PRD §3.2: "resubmitting a `REJECTED` design returns it to
        `SUBMITTED`, increments `revision_count` by 1, and clears
        `rejection_reason` back to null, and this revision loop may repeat as
        many times as needed."

        Design: Difficulty/non_linear_state_machine/design_resubmission_cycle
        """
        program = create_active_program()
        design = create_design(
            program["id"],
            name="Mascot v1",
            artwork_ref="m1.png",
            royalty_pct=0.05,
            licensing_fee_cents=2000,
        )

        submitted1 = design_transition(design["id"], "SUBMITTED", design["version"])
        rejected1 = design_transition(
            design["id"], "REJECTED", submitted1["version"], note="colors off-brand"
        )
        submitted2 = design_transition(design["id"], "SUBMITTED", rejected1["version"])
        rejected2 = design_transition(
            design["id"], "REJECTED", submitted2["version"], note="font not licensed"
        )
        submitted3 = design_transition(design["id"], "SUBMITTED", rejected2["version"])
        final = design_transition(design["id"], "APPROVED", submitted3["version"])

        assert final["status"] == "APPROVED", (
            f"expected APPROVED after two full REJECTED->SUBMITTED loops, "
            f"got {final['status']}"
        )
        assert final["revision_count"] == 2, (
            f"revision_count must increment exactly once per resubmission, "
            f"got {final['revision_count']}"
        )

    def test_rejection_reason_captured_then_cleared_on_resubmission(self, api):
        """PRD §3.2: "From `SUBMITTED`, the coordinator either approves it —
        the design becomes `APPROVED` and its variants can sell — or rejects
        it, supplying a `note` that is captured into `rejection_reason` while
        the design sits in `REJECTED`."
        PRD §3.2: "resubmitting a `REJECTED` design returns it to `SUBMITTED`,
        increments `revision_count` by 1, and clears `rejection_reason` back
        to null"

        Design: Difficulty/non_linear_state_machine/design_resubmission_cycle
        """
        program = create_active_program()
        design = create_design(program["id"], name="Mascot v1")
        submitted = design_transition(design["id"], "SUBMITTED", design["version"])
        rejected = design_transition(
            design["id"], "REJECTED", submitted["version"], note="colors off-brand"
        )
        assert rejected["status"] == "REJECTED"
        assert rejected["rejection_reason"] == "colors off-brand"

        resubmitted = design_transition(
            design["id"], "SUBMITTED", rejected["version"]
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1
        assert resubmitted["rejection_reason"] is None


class TestDesignTransitionGuards:
    def test_design_approve_from_draft_returns_invalid_transition(self, api):
        """PRD §3.2: "Submitting a `DRAFT` design moves it to `SUBMITTED`
        (else `ERR_INVALID_STATE_TRANSITION`)."
        PRD §2.8: "The target resource must sit in a valid from-state for the
        requested transition. State-specific errors fire here —
        `ERR_CAMPAIGN_NOT_OPEN`, `ERR_DROP_NOT_OPEN`, `ERR_DRAWER_NOT_OPEN`,
        `ERR_PREORDER_NOT_PAYABLE`, `ERR_PREORDER_NOT_CANCELLABLE`,
        `ERR_PICKUP_NOT_READY`, `ERR_PICKUP_EXPIRED`,
        `ERR_EVENT_WINDOW_PASSED`, `ERR_VENDOR_NOT_APPROVED` — and anything
        else is the generic `ERR_INVALID_STATE_TRANSITION`."

        Design: Corner/state_machines/design_approve_from_draft_returns_invalid_transition
        """
        program = create_active_program()
        design = create_design(program["id"])
        res = api.design_licensing_transition(
            design["id"],
            {"to_state": "APPROVED", "expected_design_version": design["version"]},
            COORDINATOR,
        )
        validate_error(res, ApiErrorId.ERR_INVALID_STATE_TRANSITION, 409)

    def test_treasurer_cannot_transition_design(self, api):
        """PRD §3.2: "Only a `LicensingCoordinator` may drive the licensing
        workflow — the manager who created the design cannot approve their own
        submission."
        PRD §2.8: "The role is permitted for the endpoint, including the
        customer-ownership rule of §2.1, else `ERR_UNAUTHORIZED_ROLE`."

        Design: Corner/rbac/treasurer_cannot_transition_design
        """
        program = create_active_program()
        design = create_design(program["id"])
        res = api.design_licensing_transition(
            design["id"],
            {"to_state": "SUBMITTED", "expected_design_version": design["version"]},
            TREASURER,
        )
        validate_error(res, ApiErrorId.ERR_UNAUTHORIZED_ROLE, 403)

    def test_occ_stale_design_version_on_resubmit(self, api):
        """PRD §2.7: "Every licensing transition on a design likewise requires
        `expected_design_version`, holding the client's last-observed
        `version` of the design. If a resubmission or decision was already
        recorded since that read, the design's version has advanced, and the
        transition is rejected with `ERR_STALE_VERSION` (HTTP 412) rather than
        overwriting a revision state the client never saw."

        Design: Corner/cross_cutting_layers/occ_stale_design_version_on_resubmit
        """
        program = create_active_program()
        design = create_design(program["id"])
        v1 = design["version"]
        submitted = design_transition(design["id"], "SUBMITTED", v1)
        rejected = design_transition(
            design["id"], "REJECTED", submitted["version"], note="colors"
        )

        stale_res = api.design_licensing_transition(
            design["id"],
            {"to_state": "SUBMITTED", "expected_design_version": submitted["version"]},
            COORDINATOR,
        )
        validate_error(stale_res, ApiErrorId.ERR_STALE_VERSION, 412)

        resubmitted = validate_success(
            api.design_licensing_transition(
                design["id"],
                {
                    "to_state": "SUBMITTED",
                    "expected_design_version": rejected["version"],
                },
                COORDINATOR,
            ),
            200,
        )
        assert resubmitted["status"] == "SUBMITTED"
        assert resubmitted["revision_count"] == 1
