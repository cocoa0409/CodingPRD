"""Phase sequencing, the cross-entity contract gate, milestones and the permit package."""
from test_helpers import (
    ApiErrorId, validate_success, validate_error,
    assert_phase, assert_permit_review, assert_instant_equals, CLOCK_DEFAULT_UTC,
    state_payload, create_permit_review_payload,
    setup_draft_contract_project, setup_executed_project,
    activate_phase, complete_phase, activate_and_complete_phase, activate_and_advance_phase,
    create_permit_review, read_contract, read_phase, read_project, set_clock,
    PRINCIPAL,
)

MILESTONES = {
    "SD": "2026-06-01T00:00:00Z",
    "DD": "2026-12-01T00:00:00Z",
    "CD": "2027-01-01T00:00:00Z",
    "CA": "2027-02-01T00:00:00Z",
}


class TestPhaseDependsOnContract:

    def test_phase_activation_is_refused_while_the_contract_is_still_draft(self, api):
        """PRD §3.3: "A phase leaves `NOT_STARTED` for `ACTIVE` only when the project's contract
        is in `EXECUTED` — otherwise `ERR_CONTRACT_NOT_EXECUTED` — and only when the sibling phase
        immediately preceding it in `phase_order` has already reached `COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/phase_activation_blocked_until_contract_is_executed
        """
        bundle = setup_draft_contract_project(
            project_number="XEN-001", name="Cross Entity Court", with_architect=False
        )

        response = api.set_phase_state(
            bundle["phase_ids"]["SD"], state_payload("ACTIVE"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value)

        sd = read_phase(bundle, "SD")
        assert sd["status"] == "NOT_STARTED", (
            "SD must stay NOT_STARTED: the rejection is a cross-entity gate, not a no-op"
        )
        assert read_project(bundle)["status"] == "DRAFT"

    def test_the_same_activation_succeeds_once_the_contract_is_executed(self, api):
        """PRD §3.2: "Finally, execution cascades to the project itself: a project in `DRAFT` is
        driven to `ACTIVE` by the mere fact that its contract executed."
        PRD §3.3: "A phase leaves `NOT_STARTED` for `ACTIVE` only when the project's contract is
        in `EXECUTED` — otherwise `ERR_CONTRACT_NOT_EXECUTED` — and only when the sibling phase
        immediately preceding it in `phase_order` has already reached `COMPLETED`."

        Design: Difficulty/cross_entity_state_dependency/phase_activation_blocked_until_contract_is_executed
        """
        bundle = setup_draft_contract_project(
            project_number="XEN-002", name="Cross Entity Close", with_architect=False
        )
        validate_error(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("ACTIVE"), bundle["pm_headers"]
            ),
            ApiErrorId.ERR_CONTRACT_NOT_EXECUTED.value,
        )

        contract = validate_success(
            api.set_contract_state(bundle["contract_id"], state_payload("EXECUTED"), PRINCIPAL)
        )
        assert contract["status"] == "EXECUTED"
        assert read_project(bundle)["status"] == "ACTIVE"

        sd = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("ACTIVE"), bundle["pm_headers"]
            )
        )
        assert_phase(sd)
        assert sd["status"] == "ACTIVE"


class TestPermitGateOutranksPhaseOrder:

    def test_ca_activation_without_permit_reports_the_permit_error_not_the_order_error(self, api):
        """PRD §2.7: "11. **Code and permit compliance** — `ERR_PERMIT_NOT_APPROVED`,
        `ERR_PERMIT_PHASE_NOT_READY` (409)."
        PRD §2.7: "12. **Structural constraints** — `ERR_DUPLICATE_PROJECT_NUMBER`,
        `ERR_CONTRACT_ALREADY_EXISTS`, `ERR_DUPLICATE_PHASE_CODE`, `ERR_PHASE_WEIGHTS_INVALID`,
        `ERR_PHASE_ORDER_VIOLATION`, `ERR_DUPLICATE_SHEET_NUMBER`, `ERR_FEE_DELTA_SIGN`,
        `ERR_MAX_CLARIFICATION_ROUNDS` (409)."
        PRD §2.7: "Checks are therefore evaluated in a fixed order, and the **first** failing
        check determines the response."
        PRD §3.6: "The `CA` phase may not be activated unless the project has at least one permit
        review, on any of its phases, sitting in status `APPROVED`. Attempting to start
        construction administration without an approved permit is rejected with
        `ERR_PERMIT_NOT_APPROVED`."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_approved_outranks_phase_order_violation
        """
        bundle = setup_executed_project(project_number="SAF-001", name="Safety Studio",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        activate_phase(bundle, "DD")

        # CA violates BOTH rules at once: no APPROVED PermitReview exists (priority 11) and its
        # predecessor CD is still NOT_STARTED (priority 12).
        response = api.set_phase_state(
            bundle["phase_ids"]["CA"], state_payload("ACTIVE"), bundle["pm_headers"]
        )
        error = validate_error(response, ApiErrorId.ERR_PERMIT_NOT_APPROVED.value)
        assert error["error_id"] != ApiErrorId.ERR_PHASE_ORDER_VIOLATION.value, (
            "the earlier permit-compliance check must win over the structural-constraint check"
        )

    def test_neither_ca_nor_cd_moves_when_the_permit_gate_rejects_the_activation(self, api):
        """PRD §3.6: "The `CA` phase may not be activated unless the project has at least one
        permit review, on any of its phases, sitting in status `APPROVED`. Attempting to start
        construction administration without an approved permit is rejected with
        `ERR_PERMIT_NOT_APPROVED`."
        PRD §2.7: "Read this ordering literally."

        Design: Difficulty/priority_pair_validation_conflict/permit_not_approved_outranks_phase_order_violation
        """
        bundle = setup_executed_project(project_number="SAF-002", name="Safety Site",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        activate_phase(bundle, "DD")

        validate_error(
            api.set_phase_state(
                bundle["phase_ids"]["CA"], state_payload("ACTIVE"), bundle["pm_headers"]
            ),
            ApiErrorId.ERR_PERMIT_NOT_APPROVED.value,
        )

        assert read_phase(bundle, "CA")["status"] == "NOT_STARTED"
        assert read_phase(bundle, "CD")["status"] == "NOT_STARTED"


class TestPhaseOrderAndHoldCycle:

    def test_phase_activation_out_of_order_is_rejected(self, api):
        """PRD §3.3: "The four phases must be worked in order."
        PRD §3.3: "`DD` waits for `SD`; `CD` waits for `DD`; `CA` waits for `CD`. A violation is
        rejected with `ERR_PHASE_ORDER_VIOLATION`."

        Design: Corner/validations/phase_activation_out_of_order_is_rejected
        """
        bundle = setup_executed_project(
            project_number="SEQ-001", name="Sequence Square",
            weights=(2500, 2500, 2500, 2500), with_architect=False,
        )
        activate_phase(bundle, "SD")  # ACTIVE, deliberately not COMPLETED

        response = api.set_phase_state(
            bundle["phase_ids"]["DD"], state_payload("ACTIVE"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PHASE_ORDER_VIOLATION.value)

        assert read_phase(bundle, "DD")["status"] == "NOT_STARTED"

    def test_on_hold_round_trip_preserves_percent_complete_and_allocation(self, api):
        """PRD §3.3: "An `ACTIVE` phase may be parked at `ON_HOLD` and later returned to `ACTIVE`
        — the loop between the two may repeat as many times as the job demands — although
        returning from `ON_HOLD` re-checks that the contract is still `EXECUTED`."
        PRD §3.3: "Each such update immediately recomputes that phase's `earned_cents` from its
        `fee_allocation_cents` and the new percentage, then recomputes the contract's
        `earned_to_date_cents` and `wip_balance_cents`, bumping `Contract.version` by one."

        Design: Corner/state_machines/phase_on_hold_and_back_to_active_cycle_preserves_percent_complete
        """
        bundle = setup_executed_project(project_number="HLD-001", name="Hold House",
                                        with_architect=False)
        activate_and_advance_phase(bundle, "SD", 40)

        held = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("ON_HOLD"), bundle["pm_headers"]
            )
        )
        assert held["status"] == "ON_HOLD"

        resumed = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("ACTIVE"), bundle["pm_headers"]
            )
        )
        assert_phase(resumed)
        assert resumed["status"] == "ACTIVE"
        assert resumed["percent_complete"] == 40, "the hold cycle must move only the status"
        assert resumed["fee_allocation_cents"] == 2_000_000
        assert resumed["earned_cents"] == 800_000  # 2_000_000 * 40 / 100

        assert read_contract(bundle)["earned_to_date_cents"] == 800_000


class TestMilestoneJudgement:

    def test_milestone_is_missed_after_the_due_instant_and_met_before_it(self, api):
        """PRD §3.3: "The milestone is then judged: `milestone_status` becomes `MET` when the
        logical clock at the moment of completion is at or before `milestone_due_at`, and `MISSED`
        when the clock has passed it."
        PRD §2.4: "Before the clock has ever been set, it reads exactly `2026-05-01T00:00:00Z`,
        and it never falls back to real time."

        Design: Corner/state_machines/phase_milestone_marked_missed_when_completed_after_due_instant
        """
        bundle = setup_executed_project(
            project_number="MIL-001", name="Milestone Manor",
            milestone_due=MILESTONES, with_architect=False,
        )
        activate_phase(bundle, "SD")

        # Advance the clock past SD's milestone (2026-06-01) but before DD's (2026-12-01).
        set_clock("2026-07-01T00:00:00Z")

        sd = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["SD"], state_payload("COMPLETED"), bundle["pm_headers"]
            )
        )
        assert_phase(sd)
        assert sd["milestone_status"] == "MISSED"
        assert sd["percent_complete"] == 100

        activate_phase(bundle, "DD")
        dd = validate_success(
            api.set_phase_state(
                bundle["phase_ids"]["DD"], state_payload("COMPLETED"), bundle["pm_headers"]
            )
        )
        assert dd["milestone_status"] == "MET"

        # SD 2_000_000 + DD 2_000_000, both at percent_complete 100.
        assert read_contract(bundle)["earned_to_date_cents"] == 4_000_000


class TestPermitReview:

    def test_permit_submission_before_the_cd_phase_completes_is_rejected(self, api):
        """PRD §3.6: "Lodging the package with the jurisdiction moves it from `PREPARING` to
        `SUBMITTED`, and this is allowed only once the `CD` phase it references has actually
        reached `COMPLETED` — a premature submission is rejected with the same
        `ERR_PERMIT_PHASE_NOT_READY`."
        PRD §3.6: "It begins in `PREPARING` with `submission_round` at 0, `comment_count` at 0 and
        `decided_at` null."

        Design: Corner/state_machines/permit_review_submit_before_cd_phase_completed_is_rejected
        """
        bundle = setup_executed_project(project_number="PMT-001", name="Permit Place",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        activate_and_complete_phase(bundle, "DD")
        activate_phase(bundle, "CD")  # ACTIVE, deliberately not COMPLETED

        permit = validate_success(
            api.create_permit_review(
                create_permit_review_payload(bundle["phase_ids"]["CD"], permit_type="ZONING"),
                bundle["pm_headers"],
            ),
            201,
        )
        assert_permit_review(permit)
        assert permit["status"] == "PREPARING"
        assert permit["submission_round"] == 0

        response = api.set_permit_review_state(
            permit["id"], state_payload("SUBMITTED"), bundle["pm_headers"]
        )
        validate_error(response, ApiErrorId.ERR_PERMIT_PHASE_NOT_READY.value)

        rows, _ = _phase_permits(api, bundle)
        still = next(row for row in rows if row["id"] == permit["id"])
        assert still["status"] == "PREPARING"
        assert still["submission_round"] == 0

    def test_comments_and_resubmission_cycle_accumulates_submission_rounds(self, api):
        """PRD §3.6: "The firm answers the comments by driving the review to `RESUBMITTED`, which
        increments `submission_round` by 1 again."
        PRD §3.6: "From `SUBMITTED`, the jurisdiction may come back with comments: the review moves
        to `COMMENTS_ISSUED`, and the number of comments must be supplied as `comment_count`, which
        is recorded on the review (omitting it is an `ERR_INVALID_REQUEST`)."
        PRD §3.6: "Approval — `SUBMITTED → APPROVED` or `RESUBMITTED → APPROVED` — stamps
        `decided_at` from the logical clock and is terminal."

        Design: Corner/state_machines/permit_review_comments_resubmit_cycle_increments_submission_round
        """
        bundle = setup_executed_project(project_number="PMT-002", name="Permit Loop",
                                        with_architect=False)
        activate_and_complete_phase(bundle, "SD")
        activate_and_complete_phase(bundle, "DD")
        activate_and_complete_phase(bundle, "CD")

        permit = create_permit_review(bundle, permit_type="FIRE")
        pm = bundle["pm_headers"]

        submitted = validate_success(
            api.set_permit_review_state(permit["id"], state_payload("SUBMITTED"), pm)
        )
        assert submitted["submission_round"] == 1

        validate_success(
            api.set_permit_review_state(
                permit["id"], state_payload("COMMENTS_ISSUED", comment_count=3), pm
            )
        )
        validate_success(
            api.set_permit_review_state(permit["id"], state_payload("RESUBMITTED"), pm)
        )
        validate_success(
            api.set_permit_review_state(
                permit["id"], state_payload("COMMENTS_ISSUED", comment_count=1), pm
            )
        )
        validate_success(
            api.set_permit_review_state(permit["id"], state_payload("RESUBMITTED"), pm)
        )
        approved = validate_success(
            api.set_permit_review_state(permit["id"], state_payload("APPROVED"), pm)
        )
        assert_permit_review(approved)

        assert approved["status"] == "APPROVED"
        assert approved["submission_round"] == 3  # SUBMITTED + two RESUBMITTED entries
        assert approved["comment_count"] == 1, "comment_count holds the most recent value"
        # The logical clock was never repositioned in this test.
        assert_instant_equals(approved["decided_at"], CLOCK_DEFAULT_UTC, "decided_at")


def _phase_permits(api, bundle):
    from test_helpers import validate_paginated
    return validate_paginated(
        api.list_phase_permit_reviews(bundle["phase_ids"]["CD"], bundle["pm_headers"])
    )
