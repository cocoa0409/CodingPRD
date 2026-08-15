"""Advance lifecycle: the writer-status gate on approval, cancellation
bounds, the PAID -> RECOUPING auto-transition, and writer-version OCC."""
from test_helpers import (
    ApiErrorId,
    assert_advance_principal_invariant,
    create_advance,
    create_advance_payload,
    create_paid_advance,
    create_writer,
    get_writer,
    reactivate_writer,
    setup_finalized_statement,
    suspend_writer,
    validate_error,
    validate_success,
)
from test_helpers.fixtures import ADMIN, FINANCE


class TestApproveGate:
    def _suspended_writer_with_advances(self):
        writer = create_writer(legal_name="W")
        a1 = create_advance(writer["id"], 1000, agreement_ref="A1")
        a2 = create_advance(writer["id"], 2000, agreement_ref="A2")
        suspend_writer(writer["id"])
        return writer, a1, a2

    def test_advance_approve_gated_on_writer_active_rejected(self, api):
        """PRD §3.7: "Approval moves the advance from `DRAFT` to `APPROVED`, but only while the writer is `ACTIVE` — approving for a `SUSPENDED` writer is rejected with `ERR_WRITER_NOT_ACTIVE`, and approval from any state other than `DRAFT` is `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/advance_approve_gated_on_writer_active
        """
        writer, a1, a2 = self._suspended_writer_with_advances()
        resp = api.approve_advance(a2["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_WRITER_NOT_ACTIVE)

        after = validate_success(api.get_advance(a2["id"], ADMIN))
        assert after["status"] == "DRAFT", "a rejected approval must not mutate"

    def test_advance_approve_succeeds_after_reactivation(self, api):
        """PRD §3.7: "Approval moves the advance from `DRAFT` to `APPROVED`, but only while the writer is `ACTIVE` — approving for a `SUSPENDED` writer is rejected with `ERR_WRITER_NOT_ACTIVE`, and approval from any state other than `DRAFT` is `ERR_INVALID_STATE_TRANSITION`."

        Design: Difficulty/cross_entity_state_dependency/advance_approve_gated_on_writer_active
        """
        writer, a1, a2 = self._suspended_writer_with_advances()
        reactivate_writer(writer["id"])

        approved_a2 = validate_success(api.approve_advance(a2["id"], FINANCE))
        assert approved_a2["status"] == "APPROVED"
        approved_a1 = validate_success(api.approve_advance(a1["id"], FINANCE))
        assert approved_a1["status"] == "APPROVED", (
            "an advance created before the suspension still approves once the "
            "writer is ACTIVE again")


class TestCancelBounds:
    def test_advance_cancel_from_paid_rejected(self, api):
        """PRD §3.7: "A `FinanceManager` may also cancel an advance while it is still `DRAFT` or `APPROVED`, moving it to terminal `CANCELLED`; once paid, an advance can no longer be cancelled."

        Design: Corner/state_machines/advance_cancel_from_paid_rejected
        """
        writer = create_writer(legal_name="W")
        advance = create_paid_advance(writer["id"], 1000)
        assert advance["status"] == "PAID"

        resp = api.cancel_advance(advance["id"], FINANCE)
        validate_error(resp, ApiErrorId.ERR_INVALID_STATE_TRANSITION)

        after = validate_success(api.get_advance(advance["id"], ADMIN))
        assert after["status"] == "PAID"


class TestFirstRecoupmentTransition:
    def test_advance_paid_to_recouping_on_first_recoup(self, api):
        """PRD §3.7: "Status follows the money: a `PAID` advance receiving its first application while anything remains outstanding moves to `RECOUPING`, and a `RECOUPING` advance whose `outstanding_cents` reaches exactly zero moves to terminal `RECOUPED`, with the writer's `advance_outstanding_cents` recomputed on each such transition."

        Design: Corner/state_machines/advance_paid_to_recouping_on_first_recoup
        """
        # Advance 5000 @ 10000 bp; one finalized line of 2000 gives the writer
        # a 1000 final amount, all of it applied to the advance.
        ctx = setup_finalized_statement(line_grosses=(2000,),
                                        advances=((5000, None),),
                                        title="Recoup Song")
        advance = validate_success(
            api.get_advance(ctx["advances"][0]["id"], ADMIN))
        assert advance["status"] == "RECOUPING", (
            "first application with outstanding still positive")
        assert advance["recouped_cents"] == 1000
        assert advance["outstanding_cents"] == 4000
        assert_advance_principal_invariant(advance)


class TestAdvanceOptimisticConcurrency:
    def test_occ_advance_create_stale_version_rejected(self, api):
        """PRD §2.7: "Creating an Advance requires the request to carry `expected_writer_version`, holding the `version` of the target Writer as the client last observed it. If the Writer's `version` has advanced since that observation, the create is rejected with `ERR_STALE_VERSION` (HTTP 412). Both fields are non-optional on their respective creates; no other endpoint accepts or requires a version field."
        PRD §2.4: "creating a SplitSet increments the parent Work's `version` by 1, and creating an Advance increments the parent Writer's `version` by 1."

        Design: Corner/cross_cutting_layers/occ_advance_create_stale_version_rejected
        """
        writer = create_writer(legal_name="W")
        observed_version = writer["version"]

        first = validate_success(
            api.create_advance(
                create_advance_payload(writer["id"], observed_version, 1000,
                                       agreement_ref="A1"),
                ADMIN),
            201)
        assert first["status"] == "DRAFT"

        stale = api.create_advance(
            create_advance_payload(writer["id"], observed_version, 2000,
                                   agreement_ref="A2"),
            ADMIN)
        validate_error(stale, ApiErrorId.ERR_STALE_VERSION)

        fresh_version = get_writer(writer["id"])["version"]
        assert fresh_version == observed_version + 1
        second = validate_success(
            api.create_advance(
                create_advance_payload(writer["id"], fresh_version, 2000,
                                       agreement_ref="A2"),
                ADMIN),
            201)
        assert second["id"] != first["id"]
